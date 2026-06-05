"""
assistant-service — camada conversacional do Objetivo 3.

Responde perguntas em linguagem natural sobre o estado e o histórico da operação,
traduzindo-as para SQL (Bedrock, com fallback determinístico) e executando no
Athena sobre os eventos do Firehose.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import engine
from .catalog import catalog
from .config import settings
from .views import bootstrap_views

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("assistant")

_STATIC = Path(__file__).parent / "static"


def _bootstrap():
    try:
        catalog.load_overrides()
        bootstrap_views()
    except Exception as exc:  # noqa: BLE001
        log.warning("bootstrap da camada conversacional falhou: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_bootstrap, daemon=True).start()
    yield


app = FastAPI(title="DijkFood · Assistant", lifespan=lifespan)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


class AskRequest(BaseModel):
    question: str


@app.post("/chat/ask", tags=["chat"])
def ask(req: AskRequest):
    return engine.answer(req.question.strip())


@app.get("/chat/capabilities", tags=["chat"])
def capabilities():
    return {
        "bedrock_enabled": settings.USE_BEDROCK,
        "model": settings.BEDROCK_MODEL_ID if settings.USE_BEDROCK else None,
        "examples": [ex["q"] for ex in catalog.few_shots],
    }


@app.get("/chat", response_class=HTMLResponse)
@app.get("/chat/", response_class=HTMLResponse)
async def chat_ui():
    return HTMLResponse((_STATIC / "chat.html").read_text(encoding="utf-8"))
