from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Depends
import httpx
import asyncio
import aioboto3
import json

from sqlalchemy import text, bindparam, Integer, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from datetime import datetime
from urllib.parse import urljoin

from .models import (Order, OrderEvent, Restaurant, OutboxEvent, OrderItem,
                     OrderCreationRequest, OrderCreationResponse,
                     OrderUpdateRequest, OrderUpdateResponse)
from .config import settings
from .prediction import predict_eta


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
    pool_timeout=10,   # falha rápido em vez de acumular backlog por 30s (padrão)
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


async def _resolve_eta(task: "asyncio.Task | None") -> dict:
    """Resolve a predição de ETA disparada concorrentemente. Nunca levanta."""
    if task is None:
        return {"eta_minutes": settings.ETA_FALLBACK_MIN, "source": "fallback"}
    try:
        return await task
    except Exception:
        return {"eta_minutes": settings.ETA_FALLBACK_MIN, "source": "fallback"}


# ---------------------------------------------------------------------------
# Lifespan: garante que o cliente HTTP seja criado e fechado corretamente
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=1000)
    app.state.http_client = httpx.AsyncClient(timeout=5.0, limits=limits)
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
    # A predição de ETA roda CONCORRENTEMENTE com a atribuição de entregador e a
    # escrita no banco — sobrepondo-se ao I/O já existente, sem adicionar latência
    # serial ao caminho crítico (e com timeout curto + fallback internos).
    eta_task = asyncio.create_task(predict_eta(client, req.id_restaurant))

    try:
        # 1. Valida restaurante
        stmt = select(Restaurant).where(Restaurant.ID_restaurant == req.id_restaurant)
        restaurant = (await db.execute(stmt)).scalar_one_or_none()
        if restaurant is None:
            raise HTTPException(status_code=404, detail="Restaurant does not exist")

        # Captura as coordenadas antes de soltar a sessão: após db.close() o objeto ORM
        # fica detached e acessar atributos causaria DetachedInstanceError.
        # Como expire_on_commit=False, estes atributos já carregados continuam
        # acessíveis mesmo após o close().
        rest_lat = float(restaurant.lat)
        rest_lon = float(restaurant.lon)

        # Libera a conexão de volta ao pool ANTES das chamadas de rede.
        # db.commit() NÃO devolve a conexão ao pool — a AsyncSession a mantém
        # alocada até o close(). Sem este close() a conexão ficaria retida durante
        # todo o I/O de rede ao tracking-service (nearby + tentativas de PATCH
        # status), esgotando o pool (pool_size=10 + 5 overflow) sob concorrência.
        # As operações de persistência abaixo readquirem uma conexão do pool.
        await db.close()

        # 2. Busca entregador proximo
        try:
            response = await client.get(
                urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/nearby"),
                params={"lat": rest_lat, "lon": rest_lon},
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

        # 3. Tenta marcar um entregador como BUSY, se der 409 (double booking), tenta o próximo
        assigned_courier = None
        for courier in items:
            try:
                busy_response = await client.patch(
                    urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                    json={"ID_courier": courier["ID_courier"], "status": "BUSY"},
                )
                
                # Se for sucesso (200), esse é o entregador alocado
                if busy_response.status_code == 200:
                    assigned_courier = courier
                    break
                # Se for 409, outro pedido já o alocou, tenta o próximo
                elif busy_response.status_code == 409:
                    logger.info(f"Courier {courier['ID_courier']} already busy. Retrying with next closest.")
                    continue
                else:
                    busy_response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 409:
                    logger.info(f"Courier {courier['ID_courier']} already busy. Retrying with next closest.")
                    continue
                logger.exception("Tracking service error while setting courier BUSY: %s", exc.response.text)
                raise
            except httpx.RequestError:
                logger.exception("Tracking service request failed while setting courier BUSY")
                raise

        if not assigned_courier:
            raise HTTPException(status_code=409, detail="Nenhum entregador disponível no momento (conflito de alocação)")

        # 4. Persiste pedido - se falhar, tenta compensar o DynamoDB
        new_order = Order(
            created_at=datetime.now(),
            ID_restaurant=req.id_restaurant,
            ID_user=req.id_user,
            ID_courier=assigned_courier["ID_courier"],
            ID_last_state=1,
        )

        db.add(new_order)
        await db.flush()

        db.add(OrderEvent(
            changed_at=new_order.created_at,
            ID_order=new_order.ID_order,
            ID_state=new_order.ID_last_state,
        ))

        # ETA já estava sendo computada em paralelo.
        eta = await _resolve_eta(eta_task)

        items_payload = []
        if req.items:
            for item_req in req.items:
                new_item = OrderItem(
                    price=item_req.price,
                    ID_item=item_req.id_item,
                    ID_order=new_order.ID_order,
                )
                db.add(new_item)
                items_payload.append({
                    "id_item": item_req.id_item,
                    "price": float(item_req.price)
                })

        order_data = {
            "id_order": new_order.ID_order,
            "created_at": new_order.created_at.isoformat(),
            "id_restaurant": new_order.ID_restaurant,
            "id_user": new_order.ID_user,
            "id_courier": new_order.ID_courier,
            "id_last_state": new_order.ID_last_state,
            "predicted_eta_minutes": eta["eta_minutes"],
            "eta_source": eta["source"],
            "items": items_payload,
        }
        # Outbox transacional: o evento analítico é gravado na MESMA transação do pedido.
        db.add(OutboxEvent(entidade="Order", acao="CREATE", dados=order_data))
        await db.commit()

        return {
            "id_order": new_order.ID_order,
            "id_courier": assigned_courier["ID_courier"],
            "eta_minutes": eta["eta_minutes"],
            "eta_source": eta["source"],
        }

    except HTTPException:
        eta_task.cancel()
        if 'assigned_courier' in locals() and assigned_courier:
            await db.rollback()
            try:
                await client.patch(
                    urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                    json={"ID_courier": assigned_courier["ID_courier"], "status": "AVAILABLE"},
                )
            except Exception:
                logger.exception("Failed to release courier after order create error")
        raise
    except Exception as e:
        eta_task.cancel()
        await db.rollback()
        if 'assigned_courier' in locals() and assigned_courier:
            try:
                await client.patch(
                    urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                    json={"ID_courier": assigned_courier["ID_courier"], "status": "AVAILABLE"},
                )
            except Exception:
                logger.exception("Failed to release courier after order create error")
        raise HTTPException(status_code=500, detail=str(e))


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
        update_data = {
            "id_order": row_dict["id_order"],
            "id_state": row_dict["id_state"],
        }
        # Outbox transacional (mesma transação da transição de estado).
        db.add(OutboxEvent(entidade="Order", acao="UPDATE", dados=update_data))
        await db.commit()

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

        return {"id_order": row_dict["id_order"], "id_state": row_dict["id_state"]}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))