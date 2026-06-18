"""
Cliente Athena minimalista (boto3) com cache TTL em memória.

Mantemos as dependências enxutas (sem awswrangler/pandas) — o serviço só precisa
disparar SQL e materializar linhas como dicts Python. As chamadas boto3 são
síncronas; os endpoints FastAPI as executam via `asyncio.to_thread`, permitindo
disparar vários indicadores em paralelo.
"""
from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from .config import settings

_athena = boto3.client(
    "athena",
    region_name=settings.AWS_REGION,
    config=BotoConfig(retries={"max_attempts": 5, "mode": "standard"}),
)

# Cache simples: { sql: (expira_em, linhas) }
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class AthenaError(RuntimeError):
    pass


def _coerce(value: str | None, athena_type: str) -> Any:
    if value is None:
        return None
    t = athena_type.lower()
    try:
        if t in ("tinyint", "smallint", "integer", "int", "bigint"):
            return int(value)
        if t in ("float", "double", "real", "decimal"):
            return float(value)
        if t == "boolean":
            return value.lower() == "true"
    except (ValueError, TypeError):
        return value
    return value


def _wait(qid: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    delay = 0.2
    while True:
        resp = _athena.get_query_execution(QueryExecutionId=qid)
        state = resp["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = resp["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise AthenaError(f"Athena query {state}: {reason}")
        if time.time() > deadline:
            raise AthenaError("Athena query timed out")
        time.sleep(delay)
        delay = min(delay * 1.5, 2.0)


def _fetch_rows(qid: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    columns: list[dict[str, str]] = []
    paginator = _athena.get_paginator("get_query_results")
    first = True
    for page in paginator.paginate(QueryExecutionId=qid):
        meta = page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
        columns = [{"name": c["Name"], "type": c["Type"]} for c in meta]
        data_rows = page["ResultSet"]["Rows"]
        # A primeira linha da primeira página é o cabeçalho.
        start = 1 if first else 0
        first = False
        for r in data_rows[start:]:
            cells = r.get("Data", [])
            record: dict[str, Any] = {}
            for i, col in enumerate(columns):
                raw = cells[i].get("VarCharValue") if i < len(cells) else None
                record[col["name"]] = _coerce(raw, col["type"])
            rows.append(record)
    return rows


def run_query(sql: str, *, use_cache: bool = True) -> list[dict[str, Any]]:
    now = time.time()
    if use_cache:
        cached = _CACHE.get(sql)
        if cached and cached[0] > now:
            return cached[1]

    start = _athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": settings.GLUE_DATABASE},
        WorkGroup=settings.ATHENA_WORKGROUP,
    )
    qid = start["QueryExecutionId"]
    _wait(qid)
    rows = _fetch_rows(qid)

    if use_cache:
        _CACHE[sql] = (now + settings.CACHE_TTL, rows)
    return rows
