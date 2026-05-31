"""
Dispatch de eventos analíticos para o Firehose (Objetivo 3).

Esquema canônico FLAT (uma única tabela Glue/Parquet `events`):
    event_type, occurred_at, city, order_id, restaurant_id, user_id,
    courier_id, state_id, state_name, lat, lon, h3_cell, predicted_eta_s

Roda em BackgroundTasks (após o commit) — não bloqueia a resposta do endpoint.
Falhas são best-effort: a analítica nunca derruba a operação. Campos ausentes
viram null no Parquet (schema é superset).
"""
import json
from datetime import datetime, timezone

from fastapi import Request

from .config import settings

_CITY = "sao_paulo"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


async def send_event(firehose_client, event: dict):
    """Envia um evento canônico ao Firehose (DirectPut)."""
    if not settings.FIREHOSE_STREAM_NAME:
        return
    event.setdefault("occurred_at", _now_iso())
    event.setdefault("city", _CITY)
    registro = (json.dumps(event, default=str) + "\n").encode("utf-8")
    try:
        await firehose_client.put_record(
            DeliveryStreamName=settings.FIREHOSE_STREAM_NAME,
            Record={"Data": registro},
        )
    except Exception as e:
        print(f"[firehose] erro ao enviar evento {event.get('event_type')}: {e}")


async def dispatch(request: Request, event: dict):
    """Helper para BackgroundTasks: usa o client criado no lifespan."""
    await send_event(request.app.state.firehose_client, event)
