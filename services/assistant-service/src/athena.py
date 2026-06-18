"""Cliente Athena (mesmo padrão dos demais serviços analíticos)."""
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


class AthenaError(RuntimeError):
    pass


def _coerce(value, t):
    if value is None:
        return None
    t = (t or "").lower()
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


def execute(sql: str, *, ddl: bool = False, timeout: float | None = None) -> list[dict[str, Any]]:
    start = _athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": settings.GLUE_DATABASE},
        WorkGroup=settings.ATHENA_WORKGROUP,
    )
    qid = start["QueryExecutionId"]

    deadline = time.time() + (timeout or settings.QUERY_TIMEOUT)
    delay = 0.25
    while True:
        resp = _athena.get_query_execution(QueryExecutionId=qid)
        state = resp["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = resp["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise AthenaError(reason or state)
        if time.time() > deadline:
            raise AthenaError("Tempo limite da consulta excedido")
        time.sleep(delay)
        delay = min(delay * 1.4, 2.0)

    if ddl:
        return []

    rows: list[dict[str, Any]] = []
    columns: list[dict[str, str]] = []
    paginator = _athena.get_paginator("get_query_results")
    first = True
    for page in paginator.paginate(QueryExecutionId=qid, PaginationConfig={"MaxItems": settings.MAX_ROWS + 5}):
        meta = page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
        columns = [{"name": c["Name"], "type": c["Type"]} for c in meta]
        for r in page["ResultSet"]["Rows"][1 if first else 0:]:
            cells = r.get("Data", [])
            rows.append({
                col["name"]: _coerce(cells[i].get("VarCharValue") if i < len(cells) else None, col["type"])
                for i, col in enumerate(columns)
            })
        first = False
    return rows
