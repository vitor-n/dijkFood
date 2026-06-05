from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
import httpx
import asyncio
from contextlib import asynccontextmanager
import aioboto3
import json

from sqlalchemy import text, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from datetime import datetime
from urllib.parse import urljoin

from .models import (Order, OrderEvent, Restaurant, OutboxEvent,
                     OrderCreationRequest, OrderCreationResponse,
                     OrderUpdateRequest, OrderUpdateResponse)
from .config import settings
from .prediction import predict_eta


async def _resolve_eta(task: "asyncio.Task | None") -> dict:
    """Resolve a predição de ETA disparada concorrentemente. Nunca levanta."""
    if task is None:
        return {"eta_minutes": settings.ETA_FALLBACK_MIN, "source": "fallback"}
    try:
        return await task
    except Exception:
        return {"eta_minutes": settings.ETA_FALLBACK_MIN, "source": "fallback"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="DijkFood Order Service", lifespan = lifespan)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


engine = create_async_engine(
    settings.POSTGRES_ENDPOINT, 
    pool_size = 50, 
    max_overflow = 20
)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

http_client = httpx.AsyncClient()

with open("./order_update_query.sql") as f:
    UPDATE_SQL_QUERY = f.read()

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

@app.post("/order", response_model = OrderCreationResponse)
async def create_order(
    req: OrderCreationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    # A predição de ETA roda CONCORRENTEMENTE com a atribuição de entregador e a
    # escrita no banco — sobrepondo-se ao I/O já existente, sem adicionar latência
    # serial ao caminho crítico (e com timeout curto + fallback internos).
    eta_task = asyncio.create_task(predict_eta(http_client, req.id_restaurant))

    try:
        stmt = select(Restaurant).where(Restaurant.ID_restaurant == req.id_restaurant)
        restaurant_result = await db.execute(stmt)
        restaurant = restaurant_result.scalar_one_or_none()
        if restaurant is None:
            raise HTTPException(status_code = 404, detail = "Restaurant does not exist")

        response = await http_client.get(
            urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/nearby"),
            params = {"lat": float(restaurant.lat), "lon": float(restaurant.lon)},
            timeout = 2.0
        )
        response.raise_for_status()
        couriers = response.json()

        if len(couriers["Items"]) == 0:
            raise HTTPException(status_code = 404, detail = "Não temos entregadores disponíveis")

        #TODO: Implement proper loop
        for courier in couriers["Items"]:
            response = await http_client.patch(
                urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                json = {"ID_courier": courier["ID_courier"], "status": "BUSY"},
                timeout = 2.0
            )
            response.raise_for_status()
            break

        new_order = Order(
            created_at = datetime.now(),
            ID_restaurant = req.id_restaurant,
            ID_user = req.id_user,
            ID_courier = courier["ID_courier"],
            ID_last_state = 1
        )

        db.add(new_order)
        await db.flush()

        new_event = OrderEvent(
            changed_at = new_order.created_at,
            ID_order = new_order.ID_order,
            ID_state = new_order.ID_last_state
        )
        db.add(new_event)

        # ETA já estava sendo computada em paralelo.
        eta = await _resolve_eta(eta_task)

        order_data = {
            "id_order": new_order.ID_order,
            "created_at": new_order.created_at.isoformat(),
            "id_restaurant": new_order.ID_restaurant,
            "id_user": new_order.ID_user,
            "id_courier": new_order.ID_courier,
            "id_last_state": new_order.ID_last_state,
            "predicted_eta_minutes": eta["eta_minutes"],
            "eta_source": eta["source"],
        }
        # Outbox transacional: o evento analítico é gravado na MESMA transação do
        # pedido. Um publisher (Lambda) o entrega ao Firehose com retry — nenhum
        # evento se perde se o Firehose estiver indisponível.
        db.add(OutboxEvent(entidade="Order", acao="CREATE", dados=order_data))
        await db.commit()

        return {
            "id_order": new_order.ID_order,
            "id_courier": courier["ID_courier"],
            "eta_minutes": eta["eta_minutes"],
            "eta_source": eta["source"],
        }

    except HTTPException:
        eta_task.cancel()
        await db.rollback()
        raise
    except Exception as e:
        eta_task.cancel()
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/order", response_model = OrderUpdateResponse)
async def update_order(
    req: OrderUpdateRequest, 
    request: Request, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    if req.id_state < 2 or req.id_state > 6:
        raise HTTPException(status_code = 400, detail = "Invalid state for update operation")
    try:
        params = {"id_novo_estado": req.id_state, "id_pedido": req.id_order, "id_estado_antigo_esperado": req.id_state - 1}

        sql_query = text(UPDATE_SQL_QUERY)
        result = await db.execute(sql_query, params)
        
        updated_row = result.fetchone()
        
        if not updated_row:
            #TODO: add proper handling
            raise HTTPException(status_code=404, detail="Order not found or invalid status")
        
        if req.id_state == 6:
            stmt = select(Order).where(Order.ID_order == req.id_order)
            order_result = await db.execute(stmt)
            order = order_result.scalar_one_or_none()

            if order is None:
                raise HTTPException(status_code = 500, detail = "Internal error: failed to mark courier as available, aborting")
    
            response = await http_client.patch(
                urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                json = {"ID_courier": order.ID_courier, "status": "AVAILABLE"},
                timeout = 2.0
            )
            response.raise_for_status()

        row_dict = updated_row._mapping
        update_data = {
            "id_order": row_dict["id_order"],
            "id_state": row_dict["id_state"],
        }
        # Outbox transacional (mesma transação da transição de estado).
        db.add(OutboxEvent(entidade="Order", acao="UPDATE", dados=update_data))
        await db.commit()

        return {"id_order": row_dict["id_order"], "id_state": row_dict["id_state"]}
        
    except Exception as e:
        await db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
