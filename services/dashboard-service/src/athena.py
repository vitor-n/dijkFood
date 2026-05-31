"""
Executor de consultas Athena para o dashboard analítico (Objetivo 3).

boto3 é síncrono; como o dashboard é FastAPI (async), as chamadas rodam em
threadpool (`asyncio.to_thread`) para não bloquear o event loop. Resultados
ficam em cache em memória por `CACHE_TTL` segundos (o dashboard é leitura
agregada, então cache curto reduz custo de scan sem perder atualidade).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import boto3

from .config import settings


class AthenaClient:
    def __init__(self):
        self._client = boto3.client("athena", region_name=settings.AWS_REGION)
        self._cache: dict[str, tuple[float, Any]] = {}

    def _run_sync(self, sql: str) -> list[dict[str, str | None]]:
        qid = self._client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": settings.GLUE_DATABASE},
            WorkGroup=settings.ATHENA_WORKGROUP,
        )["QueryExecutionId"]

        deadline = time.time() + settings.QUERY_TIMEOUT
        state = "QUEUED"
        while time.time() < deadline:
            info = self._client.get_query_execution(QueryExecutionId=qid)
            state = info["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.5)

        if state != "SUCCEEDED":
            reason = (
                info["QueryExecution"]["Status"].get("StateChangeReason", "")
                if "info" in dir()
                else ""
            )
            raise RuntimeError(f"Athena query {state}: {reason}")

        # Pagina os resultados; a 1ª linha é o cabeçalho.
        rows: list[dict[str, str | None]] = []
        header: list[str] | None = None
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"QueryExecutionId": qid, "MaxResults": 1000}
            if token:
                kwargs["NextToken"] = token
            resp = self._client.get_query_results(**kwargs)
            data = resp["ResultSet"]["Rows"]
            for i, r in enumerate(data):
                vals = [c.get("VarCharValue") for c in r["Data"]]
                if header is None:
                    header = vals
                    continue
                rows.append(dict(zip(header, vals)))
            token = resp.get("NextToken")
            if not token:
                break
        return rows

    async def query(self, key: str, sql: str) -> list[dict[str, str | None]]:
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < settings.CACHE_TTL:
            return cached[1]
        rows = await asyncio.to_thread(self._run_sync, sql)
        self._cache[key] = (now, rows)
        return rows
