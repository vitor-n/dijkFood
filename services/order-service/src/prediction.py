"""
Cliente do prediction-service para ETA no momento do pedido.

Chamado no caminho de criação do pedido com timeout curto e fallback
determinístico: a predição é informativa e JAMAIS pode regredir a latência ou a
disponibilidade da operação (requisito não-funcional). Em qualquer falha/timeout
do modelo, retorna o fallback configurado.
"""
from __future__ import annotations

import httpx

from .config import settings


async def predict_eta(client: httpx.AsyncClient, id_restaurant: int) -> dict:
    """Retorna {eta_minutes, source}. Nunca levanta exceção."""
    try:
        resp = await client.post(
            settings.PREDICTION_SERVICE_ENDPOINT.rstrip("/") + "/predict/eta",
            json={"id_restaurant": id_restaurant},
            timeout=settings.ETA_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        eta = body.get("eta_minutes")
        if eta is not None:
            return {"eta_minutes": round(float(eta), 1), "source": body.get("source", "model")}
    except Exception:
        pass
    return {"eta_minutes": settings.ETA_FALLBACK_MIN, "source": "fallback"}
