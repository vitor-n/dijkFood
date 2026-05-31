"""
Executor de consultas Athena para a camada preditiva (Objetivo 3).

Reusa o padrão do dashboard: boto3 síncrono em threadpool, sem bloquear o loop.
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

    def _run_sync(self, sql: str) -> list[dict[str, str | None]]:
        qid = self._client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": settings.GLUE_DATABASE},
            WorkGroup=settings.ATHENA_WORKGROUP,
        )["QueryExecutionId"]

        deadline = time.time() + settings.QUERY_TIMEOUT
        state, info = "QUEUED", None
        while time.time() < deadline:
            info = self._client.get_query_execution(QueryExecutionId=qid)
            state = info["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.5)

        if state != "SUCCEEDED":
            reason = info["QueryExecution"]["Status"].get("StateChangeReason", "") if info else ""
            raise RuntimeError(f"Athena query {state}: {reason}")

        rows: list[dict[str, str | None]] = []
        header: list[str] | None = None
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"QueryExecutionId": qid, "MaxResults": 1000}
            if token:
                kwargs["NextToken"] = token
            resp = self._client.get_query_results(**kwargs)
            for r in resp["ResultSet"]["Rows"]:
                vals = [c.get("VarCharValue") for c in r["Data"]]
                if header is None:
                    header = vals
                    continue
                rows.append(dict(zip(header, vals)))
            token = resp.get("NextToken")
            if not token:
                break
        return rows

    async def query(self, sql: str) -> list[dict[str, str | None]]:
        return await asyncio.to_thread(self._run_sync, sql)
