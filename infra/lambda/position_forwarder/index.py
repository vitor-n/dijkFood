"""
position-forwarder — CDC da camada analítica (Objetivo 3).

Consome o DynamoDB Stream da tabela CourierTracking (NEW_AND_OLD_IMAGES) e
encaminha cada posição/atualização de courier como um evento canônico para o
Firehose da plataforma (mesma tabela/schema dos demais eventos). Roda fora do
caminho quente da operação: nenhuma latência é adicionada ao
POST /tracking/position.

O evento segue o schema canônico flat (igual ao emitido pelos serviços):
    event_type=courier_position, occurred_at, city, courier_id, state_name,
    lat, lon, h3_cell

Variáveis de ambiente:
    FIREHOSE_STREAM_NAME   nome do delivery stream do Firehose
    CITY                   rótulo da cidade (default "sao_paulo")
"""
import json
import os
from datetime import datetime, timezone

import boto3

FIREHOSE_STREAM_NAME = os.environ["FIREHOSE_STREAM_NAME"]
CITY = os.environ.get("CITY", "sao_paulo")

_firehose = boto3.client("firehose")


def _num(value):
    """DynamoDB number ('N') chega como string; converte para float/int seguro."""
    if value is None:
        return None
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def _image_to_event(image: dict) -> dict | None:
    """Converte a NewImage do stream (formato DynamoDB JSON) em evento canônico."""
    if not image:
        return None

    def g(attr):
        cell = image.get(attr)
        if not cell:
            return None
        # cada atributo é {"N": "..."} | {"S": "..."} | {"BOOL": ...}
        return next(iter(cell.values()))

    courier_id = _num(g("ID_courier"))
    if courier_id is None:
        return None

    return {
        "event_type": "courier_position",
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "city": CITY,
        "courier_id": courier_id,
        "state_name": g("status"),
        "lat": _num(g("lat")),
        "lon": _num(g("lon")),
        "h3_cell": g("cell_index"),
    }


def handler(event, context):
    records = event.get("Records", [])

    # Redução de volume/custo (sem perda analítica relevante): posições chegam a
    # cada 100ms; o dashboard não precisa de cada ponto. Colapsamos para a
    # ÚLTIMA posição por courier nesta invocação. Combinado com uma janela de
    # batching maior no event source mapping, corta o volume em ordens de
    # magnitude (e mantém o Firehose DirectPut bem abaixo do limite de ~5k rec/s).
    latest: dict[int, dict] = {}
    for rec in records:
        if rec.get("eventName") == "REMOVE":
            continue
        canonical = _image_to_event(rec.get("dynamodb", {}).get("NewImage"))
        if canonical is None:
            continue
        # Stream é cronológico por shard → a última ocorrência vence.
        latest[canonical["courier_id"]] = canonical

    entries = [{"Data": (json.dumps(ev) + "\n").encode("utf-8")} for ev in latest.values()]

    if not entries:
        return {"forwarded": 0}

    forwarded = 0
    # PutRecordBatch aceita até 500 registros por chamada — envia em lotes.
    for i in range(0, len(entries), 500):
        batch = entries[i:i + 500]
        resp = _firehose.put_record_batch(
            DeliveryStreamName=FIREHOSE_STREAM_NAME,
            Records=batch,
        )
        forwarded += len(batch) - resp.get("FailedPutCount", 0)

    return {"forwarded": forwarded, "received": len(records)}
