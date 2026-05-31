"""
prediction-service — capacidade preditiva (Objetivo 3).

Prediz o tempo de entrega no momento do pedido. Treina a partir do data lake
(Athena) e serve de um modelo persistido no S3. Roteado pelo ALB em /predict*.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from .athena import AthenaClient
from .config import settings
from .model import DeliveryTimeModel
from .queries import TRAINING_FEATURES, MONITORING_MAE

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("prediction-service")

athena = AthenaClient()
model = DeliveryTimeModel()


async def _train() -> dict:
    rows = await athena.query(TRAINING_FEATURES)
    result = await asyncio.to_thread(model.train, rows)
    return result.__dict__


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deploy: tenta carregar o modelo já treinado (rápido, não bloqueia health).
    loaded = await asyncio.to_thread(model.load_from_s3)
    if not loaded and settings.TRAIN_ON_STARTUP:
        # Treina em background para o health check passar imediatamente.
        asyncio.create_task(_safe_initial_train())
    yield


async def _safe_initial_train():
    try:
        res = await _train()
        log.info("Treino inicial: %s", res)
    except Exception as exc:
        log.warning("Treino inicial falhou (seguirá com fallback): %s", exc)


app = FastAPI(title="DijkFood Prediction Service", lifespan=lifespan)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.get("/predict/healthz", tags=["ops"])
async def healthz_prefixed():
    return {"status": "ok", "model_ready": model.ready}


@app.get("/predict/delivery-time", tags=["predict"])
async def predict_delivery_time(
    restaurant_id: int | None = Query(default=None),
    h3_cell: str | None = Query(default=None),
    hour: int | None = Query(default=None, ge=0, le=23),
    dow: int | None = Query(default=None, ge=1, le=7),
):
    now = datetime.now(timezone.utc)
    hour = now.hour if hour is None else hour
    dow = now.isoweekday() if dow is None else dow

    secs = model.predict_seconds(hour, dow, restaurant_id, h3_cell)
    if secs is None:
        # Modelo ainda não treinado: o cliente deve aplicar seu fallback.
        return {"predicted_eta_s": None, "model_ready": False, "source": "unavailable"}
    return {"predicted_eta_s": round(secs, 1), "model_ready": True, "source": "model"}


@app.post("/predict/train", tags=["lifecycle"])
async def train_endpoint():
    """Dispara o (re)treino: coleta features no Athena, treina e publica no S3."""
    try:
        return await _train()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no treino: {exc}") from exc


@app.get("/predict/metrics", tags=["lifecycle"])
async def metrics_endpoint():
    """Monitoramento: MAE entre ETA previsto e tempo real de entrega."""
    try:
        rows = await athena.query(MONITORING_MAE)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no Athena: {exc}") from exc
    row = rows[0] if rows else {}
    return {"n": row.get("n"), "mae_seconds": row.get("mae_seconds"), "model_ready": model.ready}
