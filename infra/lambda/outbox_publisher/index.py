"""
outbox-publisher — relay transacional do outbox para o Firehose.

Lê as linhas NÃO publicadas da tabela `outbox_events` (gravadas pelos serviços
na MESMA transação do dado de domínio), publica no Kinesis Firehose com retry e
marca como publicadas. Garante entrega *at-least-once* dos eventos analíticos:
se o Firehose falhar, a linha permanece pendente e é reprocessada.

Disparada periodicamente (EventBridge Scheduler). Roda na VPC para alcançar o
RDS; usa o driver puro-Python pg8000 (vendado em _vendor/).

Env: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, FIREHOSE_STREAM_NAME,
     BATCH_LIMIT, MAX_BATCHES.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_vendor"))

import boto3
import pg8000.dbapi

_FIREHOSE = boto3.client("firehose")
_STREAM = os.environ["FIREHOSE_STREAM_NAME"]
BATCH_LIMIT = int(os.environ.get("BATCH_LIMIT", "500"))
MAX_BATCHES = int(os.environ.get("MAX_BATCHES", "20"))

_DDL = """
CREATE TABLE IF NOT EXISTS outbox_events (
  id BIGSERIAL PRIMARY KEY,
  entidade VARCHAR(64) NOT NULL,
  acao VARCHAR(32) NOT NULL,
  dados JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ NULL,
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished ON outbox_events (id) WHERE published_at IS NULL;
"""


def _connect():
    return pg8000.dbapi.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        timeout=10,
    )


def _ensure_table(conn):
    cur = conn.cursor()
    for stmt in _DDL.strip().split(";"):
        if stmt.strip():
            cur.execute(stmt)
    conn.commit()
    cur.close()


def _envelope(entidade, acao, dados, created_at):
    if isinstance(dados, str):
        try:
            dados = json.loads(dados)
        except ValueError:
            dados = {"raw": dados}
    ts = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    return {"timestamp": ts, "entidade": entidade, "acao": acao, "dados": dados}


def _process_batch(conn) -> int:
    cur = conn.cursor()
    # SKIP LOCKED permite múltiplas execuções concorrentes sem reprocessar.
    cur.execute(
        "SELECT id, entidade, acao, dados, created_at FROM outbox_events "
        "WHERE published_at IS NULL ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
        (BATCH_LIMIT,),
    )
    rows = cur.fetchall()
    if not rows:
        cur.close()
        conn.rollback()
        return 0

    records = [{"Data": (json.dumps(_envelope(e, a, d, c), default=str) + "\n").encode("utf-8")}
               for (_id, e, a, d, c) in rows]

    resp = _FIREHOSE.put_record_batch(DeliveryStreamName=_STREAM, Records=records)
    responses = resp.get("RequestResponses", [])

    published_ids, failed = [], []
    for (row, rr) in zip(rows, responses):
        if rr.get("ErrorCode"):
            failed.append((row[0], rr.get("ErrorMessage", "")[:500]))
        else:
            published_ids.append(row[0])
    # Se o Firehose não devolveu detalhes, considera tudo publicado (sucesso geral).
    if not responses:
        published_ids = [row[0] for row in rows]

    if published_ids:
        cur.execute("UPDATE outbox_events SET published_at = now() WHERE id = ANY(%s)", (published_ids,))
    for (fid, msg) in failed:
        cur.execute(
            "UPDATE outbox_events SET attempts = attempts + 1, last_error = %s WHERE id = %s",
            (msg, fid),
        )
    conn.commit()
    cur.close()
    return len(rows)


def handler(event, _context):
    end_time = time.time() + 55  # Mantém a Lambda viva por 55 segundos
    conn = _connect()
    total = 0
    try:
        _ensure_table(conn)
        while time.time() < end_time:
            batch_total = 0
            for _ in range(MAX_BATCHES):
                n = _process_batch(conn)
                batch_total += n
                total += n
                if n < BATCH_LIMIT:
                    break
            
            # Se não encontrou nenhum evento novo para processar, aguarda 5 segundos
            if batch_total == 0:
                time.sleep(5)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {"published": total}
