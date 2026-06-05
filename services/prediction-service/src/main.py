"""
prediction-service — capacidade preditiva do Objetivo 3.

Serve ETA de forma síncrona (modelo em memória, com fallback determinístico) e
expõe o ciclo de vida do modelo (coleta → treino → implantação → monitoramento),
além das previsões de demanda e anomalias (batch) materializadas no S3.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import batch
from .config import settings
from .model import eta_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("prediction")


def _bootstrap():
    """Carrega o modelo do S3; se não houver, treina (auto) sem bloquear o health."""
    if eta_model.load_from_s3():
        return
    if settings.AUTO_TRAIN_ON_START:
        try:
            log.info("Sem modelo no S3 — treinando a partir da camada analítica...")
            eta_model.train(source="in-container")
        except Exception as exc:  # noqa: BLE001
            log.warning("Auto-treino falhou (seguindo com fallback): %s", exc)


def _reload_loop():
    while True:
        time.sleep(settings.MODEL_RELOAD_SECONDS)
        try:
            eta_model.load_from_s3()
        except Exception as exc:  # noqa: BLE001
            log.warning("Reload do modelo falhou: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_bootstrap, daemon=True).start()
    threading.Thread(target=_reload_loop, daemon=True).start()
    yield


app = FastAPI(title="DijkFood · Prediction Service", lifespan=lifespan)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok", "model_ready": eta_model.is_ready}


# ── Serving: ETA síncrono ─────────────────────────────────────────────────────
class ETARequest(BaseModel):
    id_restaurant: int | None = None
    id_user: int | None = None
    created_at: str | None = None  # ISO8601; default = agora (UTC)


@app.post("/predict/eta", tags=["predict"])
def predict_eta(req: ETARequest):
    if req.created_at:
        try:
            ts = datetime.fromisoformat(req.created_at.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    result = eta_model.predict(req.id_restaurant, ts.hour, ts.isoweekday())
    result["id_restaurant"] = req.id_restaurant
    result["predicted_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ── Ciclo de vida do modelo ───────────────────────────────────────────────────
@app.post("/train/eta", tags=["lifecycle"])
def train_eta(source: str = "in-container"):
    try:
        metrics = eta_model.train(source=source)
        return {"status": "trained", "metrics": metrics}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/model/info", tags=["lifecycle"])
def model_info():
    return eta_model.info()


@app.post("/model/reload", tags=["lifecycle"])
def model_reload():
    """Recarrega o artefato do S3 (usado pela pipeline gerenciada após retreino)."""
    ok = eta_model.load_from_s3()
    return {"reloaded": ok, **eta_model.info()}


# ── Batch: demanda + anomalias ────────────────────────────────────────────────
@app.post("/batch/run", tags=["batch"])
def run_batch():
    try:
        return {"status": "ok", **batch.run_and_store()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/predict/demand", tags=["predict"])
def get_demand():
    return batch.read_demand()


@app.get("/predict/anomalies", tags=["predict"])
def get_anomalies():
    return batch.read_anomalies()
