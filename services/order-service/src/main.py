from fastapi import FastAPI, HTTPException, Depends
import httpx
import h3
from contextlib import asynccontextmanager
import aioboto3

from sqlalchemy import text, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from datetime import datetime
from urllib.parse import urljoin

from .models import (Order, OrderEvent, Restaurant,
                     OrderCreationRequest, OrderCreationResponse,
                     OrderUpdateRequest, OrderUpdateResponse)
from .config import settings
from .events import EventEmitter

# Mapa id_state -> nome (espelha OrderState do schema), usado nos eventos.
STATE_NAMES = {
    1: "CONFIRMED", 2: "PREPARING", 3: "READY_FOR_PICKUP",
    4: "PICKED_UP", 5: "IN_TRANSIT", 6: "DELIVERED",
}

# Emissor analítico assíncrono e limitado (ver events.py).
emitter = EventEmitter(settings.FIREHOSE_STREAM_NAME, sample_rate=settings.PREDICTION_SAMPLE_RATE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    session = aioboto3.Session()
    async with session.client("firehose", region_name=settings.AWS_REGION) as firehose_client:
        app.state.firehose_client = firehose_client
        emitter.bind(firehose_client, predictor=get_predicted_eta)
        await emitter.start()
        try:
            yield
        finally:
            await emitter.stop()

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


async def get_predicted_eta(restaurant_id: int, h3_cell: str | None) -> float | None:
    """Consulta o prediction-service (Objetivo 3). Best-effort: timeout curto;
    qualquer falha → None (a predição é enriquecimento, nunca caminho crítico)."""
    if not settings.PREDICTION_SERVICE_ENDPOINT:
        return None
    try:
        resp = await http_client.get(
            urljoin(settings.PREDICTION_SERVICE_ENDPOINT, "predict/delivery-time"),
            params={"restaurant_id": restaurant_id, "h3_cell": h3_cell or ""},
            timeout=settings.PREDICTION_TIMEOUT_S,
        )
        if resp.status_code == 200:
            return resp.json().get("predicted_eta_s")
    except Exception:
        return None
    return None


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

@app.post("/order", response_model = OrderCreationResponse)
async def create_order(
    req: OrderCreationRequest,
    db: AsyncSession = Depends(get_db)
):

    stmt = select(Restaurant).where(Restaurant.ID_restaurant == req.id_restaurant)
    restaurant_result = await db.execute(stmt)
    restaurant = restaurant_result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code = 404, detail = "Restaurant does not exist")
    
    print("restaurante existe:", restaurant.lat, restaurant.lon)


    response = await http_client.get(
        urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/nearby"),
        params = {"lat": float(restaurant.lat), "lon": float(restaurant.lon)},
        timeout = 2.0
    )

    if response.status_code == 422:
        print("Detalhes da rejeição do FastAPI:", response.text)

    response.raise_for_status()
    couriers = response.json()

    if len(couriers["Items"]) == 0:
        raise HTTPException(status_code = 404, detail = "Não temos entregadores disponíveis")

    # Atribuição ATÔMICA: tenta reivindicar cada candidato até um sucesso. O
    # claim (UpdateItem condicional AVAILABLE→BUSY) evita a corrida em que dois
    # pedidos concorrentes pegam o mesmo entregador (o /nearby pode estar
    # desatualizado sob concorrência).
    courier = None
    for candidate in couriers["Items"]:
        response = await http_client.post(
            urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/claim"),
            json = {"ID_courier": candidate["ID_courier"]},
            timeout = 2.0
        )
        response.raise_for_status()
        if response.json().get("claimed"):
            courier = candidate
            break

    if courier is None:
        raise HTTPException(status_code = 409, detail = "Entregadores disponíveis foram reivindicados por outros pedidos")

    try:
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
        await db.commit()
        
        # Emissão analítica O(1) e não-bloqueante (fila limitada). predict=True
        # marca o evento p/ enriquecimento com ETA previsto (amostrado/limitado
        # no worker), sem qualquer chamada de rede no caminho quente.
        r_lat, r_lon = float(restaurant.lat), float(restaurant.lon)
        emitter.emit({
            "event_type": "order_created",
            "order_id": new_order.ID_order,
            "restaurant_id": new_order.ID_restaurant,
            "user_id": new_order.ID_user,
            "courier_id": new_order.ID_courier,
            "state_id": 1,
            "state_name": "CONFIRMED",
            "lat": r_lat,
            "lon": r_lon,
            "h3_cell": h3.latlng_to_cell(r_lat, r_lon, 8),
        }, predict=True)

        return {"id_order": new_order.ID_order, "id_courier": courier["ID_courier"]}
        
    except Exception as e:

        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/order", response_model = OrderUpdateResponse)
async def update_order(
    req: OrderUpdateRequest,
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

        await db.commit()
        row_dict = updated_row._mapping
        
        # Emissão analítica O(1) e não-bloqueante (fila limitada).
        emitter.emit({
            "event_type": "order_state_changed",
            "order_id": row_dict["id_order"],
            "state_id": row_dict["id_state"],
            "state_name": STATE_NAMES.get(row_dict["id_state"]),
        })

        return {"id_order": row_dict["id_order"], "id_state": row_dict["id_state"]}
        
    except Exception as e:
        await db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
