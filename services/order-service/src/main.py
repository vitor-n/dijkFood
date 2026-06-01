from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Depends
import httpx

from sqlalchemy import text, bindparam, Integer, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from datetime import datetime
from urllib.parse import urljoin

from .models import (Order, OrderEvent, Restaurant,
                     OrderCreationRequest, OrderCreationResponse,
                     OrderUpdateRequest, OrderUpdateResponse)
from .config import settings


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine - pool calibrado para async: conexões são reutilizadas pelo event loop
# pool_pre_ping: valida conexão antes de usar (essencial para RDS)
# pool_recycle:  descarta conexões ociosas após 5 min (RDS mata após ~8h)
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.POSTGRES_ENDPOINT,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Pré-compilar a query com tipos explícitos elimina os CASTs do SQL
with open("./order_update_query.sql") as f:
    _raw_sql = f.read()

UPDATE_SQL_QUERY = text(_raw_sql).bindparams(
    bindparam("id_novo_estado",           type_=Integer()),
    bindparam("id_pedido",                type_=Integer()),
    bindparam("id_estado_antigo_esperado", type_=Integer()),
)


# ---------------------------------------------------------------------------
# Lifespan: garante que o cliente HTTP seja criado e fechado corretamente
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=5.0)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="DijkFood Order Service", lifespan=lifespan)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


async def get_db():
    async with async_session() as session:
        yield session  # async with ja fecha


def get_http_client() -> httpx.AsyncClient:
    return app.state.http_client


# ---------------------------------------------------------------------------
# POST /order
# ---------------------------------------------------------------------------
@app.post("/order", response_model=OrderCreationResponse)
async def create_order(
    req: OrderCreationRequest,
    db: AsyncSession = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    # 1. Valida restaurante
    stmt = select(Restaurant).where(Restaurant.ID_restaurant == req.id_restaurant)
    restaurant = (await db.execute(stmt)).scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant does not exist")

    # 2. Busca entregador proximo
    try:
        response = await client.get(
            urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/nearby"),
            params={"lat": float(restaurant.lat), "lon": float(restaurant.lon)},
        )
    except httpx.RequestError:
        logger.exception("Tracking service request failed while fetching nearby couriers")
        raise
    if response.status_code == 422:
        logger.error("Tracking service rejected request: %s", response.text)
        raise HTTPException(status_code=502, detail=f"Tracking service rejected request: {response.text}")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        logger.exception("Tracking service error while fetching nearby couriers: %s", response.text)
        raise

    items = response.json().get("Items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Nenhum entregador disponível")

    # 3. Marca o primeiro entregador como BUSY
    courier = items[0]
    try:
        busy_response = await client.patch(
            urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
            json={"ID_courier": courier["ID_courier"], "status": "BUSY"},
        )
    except httpx.RequestError:
        logger.exception("Tracking service request failed while setting courier BUSY")
        raise
    try:
        busy_response.raise_for_status()
    except httpx.HTTPStatusError:
        logger.exception("Tracking service error while setting courier BUSY: %s", busy_response.text)
        raise

    # 4. Persiste pedido - se falhar, tenta compensar o DynamoDB
    try:
        new_order = Order(
            created_at=datetime.now(),
            ID_restaurant=req.id_restaurant,
            ID_user=req.id_user,
            ID_courier=courier["ID_courier"],
            ID_last_state=1,
        )
        db.add(new_order)
        await db.flush()

        db.add(OrderEvent(
            changed_at=new_order.created_at,
            ID_order=new_order.ID_order,
            ID_state=new_order.ID_last_state,
        ))
        await db.commit()

    except Exception as e:
        await db.rollback()
        # Libera entregador se o banco falhou
        try:
            await client.patch(
                urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                json={"ID_courier": courier["ID_courier"], "status": "AVAILABLE"},
            )
        except Exception:
            logger.exception("Failed to release courier after order create error")
        raise HTTPException(status_code=500, detail=str(e))

    return {"id_order": new_order.ID_order, "id_courier": courier["ID_courier"]}


# ---------------------------------------------------------------------------
# PATCH /order
# ---------------------------------------------------------------------------
@app.patch("/order", response_model=OrderUpdateResponse)
async def update_order(
    req: OrderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    if req.id_state < 2 or req.id_state > 6:
        raise HTTPException(status_code=400, detail="Invalid state for update operation")

    try:
        result = await db.execute(
            UPDATE_SQL_QUERY,
            {"id_novo_estado": req.id_state, "id_pedido": req.id_order,
             "id_estado_antigo_esperado": req.id_state - 1},
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Order not found or invalid status transition")

        row_dict = row._mapping

        if req.id_state == 6:
            try:
                response = await client.patch(
                    urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                    json={"ID_courier": row_dict["id_courier"], "status": "AVAILABLE"},
                )
            except httpx.RequestError:
                logger.exception("Tracking service request failed while setting courier AVAILABLE")
                raise
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.exception("Tracking service error while setting courier AVAILABLE: %s", response.text)
                raise

        await db.commit()
        return {"id_order": row_dict["id_order"], "id_state": row_dict["id_state"]}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))