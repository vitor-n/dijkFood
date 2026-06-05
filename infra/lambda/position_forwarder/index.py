"""
position-forwarder — CDC das posições dos entregadores para o Data Lake.

Disparada pelo DynamoDB Stream da tabela CourierTracking (NEW_IMAGE), converte
cada posição reportada no MESMO envelope de evento usado pelos microsserviços e
publica no Kinesis Firehose. Assim, "posições reportadas" passam a ser persistidas
de forma durável na camada analítica, sem acoplar a operação (caminho assíncrono).

Envelope (idêntico ao services/*/firehose.py):
    {"timestamp": <iso8601>, "entidade": "Position", "acao": "REPORT", "dados": {...}}

Variáveis de ambiente:
    FIREHOSE_STREAM_NAME  — nome do delivery stream de destino.
"""
import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeDeserializer

_DESERIALIZER = TypeDeserializer()
_FIREHOSE = boto3.client("firehose")
_STREAM = os.environ["FIREHOSE_STREAM_NAME"]


def _to_native(image: dict) -> dict:
    """Converte um NEW_IMAGE do DynamoDB Stream em dict Python puro."""
    out = {}
    for key, typed_value in image.items():
        try:
            out[key] = _DESERIALIZER.deserialize(typed_value)
        except Exception:
            out[key] = None
    return out


def _normalize(dados: dict) -> dict:
    """Decimais do DynamoDB -> tipos serializáveis e nomes consistentes."""
    def _num(v):
        if v is None:
            return None
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return v

    return {
        "id_courier": _num(dados.get("ID_courier")),
        "lat": _num(dados.get("lat")),
        "lon": _num(dados.get("lon")),
        "status": dados.get("status"),
        "cell_index": dados.get("cell_index"),
        "updated_at": _num(dados.get("updated_at")),
    }


def handler(event, _context):
    records = []
    for rec in event.get("Records", []):
        if rec.get("eventName") not in ("INSERT", "MODIFY"):
            continue
        image = rec.get("dynamodb", {}).get("NewImage")
        if not image:
            continue

        dados = _normalize(_to_native(image))

        # Sem posição válida (ex.: só mudança de status sem lat/lon) — ainda assim
        # é um evento operacional útil; mantemos.
        updated_ms = dados.get("updated_at")
        if isinstance(updated_ms, (int, float)) and updated_ms > 0:
            ts = datetime.fromtimestamp(updated_ms / 1000.0, tz=timezone.utc).isoformat()
        else:
            ts = datetime.now(timezone.utc).isoformat()

        envelope = {
            "timestamp": ts,
            "entidade": "Position",
            "acao": "REPORT",
            "dados": dados,
        }
        records.append({"Data": (json.dumps(envelope, default=str) + "\n").encode("utf-8")})

    # Firehose PutRecordBatch aceita no máximo 500 registros por chamada.
    sent = 0
    for i in range(0, len(records), 500):
        batch = records[i:i + 500]
        if not batch:
            continue
        resp = _FIREHOSE.put_record_batch(
            DeliveryStreamName=_STREAM,
            Records=batch,
        )
        sent += len(batch) - resp.get("FailedPutCount", 0)

    return {"received": len(event.get("Records", [])), "forwarded": sent}
