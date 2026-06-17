"""
dashboard-service — camada analítica (Arquitetura Lambda) do DijkFood.

Serve os 6 indicadores obrigatórios + métricas de estado instantâneo + painel
preditivo. Os indicadores históricos pesados vêm da BATCH layer (tabelas Parquet
`mart_*`, pré-agregadas pelo Glue → varredura mínima); os indicadores "vivos"
vêm da SPEED layer (tabela crua `events`, janela curta). O "volume no tempo" é a
reconciliação batch+speed. A UI (Plotly) é servida estaticamente.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import boto3
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from . import queries as Q
from .athena import run_query
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dashboard")

app = FastAPI(title="DijkFood · Dashboard Analítico")

_STATIC = Path(__file__).parent / "static"
_s3 = boto3.client("s3", region_name=settings.AWS_REGION)


def _read_pred_json(key: str) -> dict[str, Any]:
    """Lê uma previsão materializada pelo prediction-service direto do S3.

    Desacopla o dashboard do prediction-service (ele pode rodar isolado numa EC2):
    a camada preditiva publica em s3://<bucket>/predictions/*, o dashboard lê dali.
    """
    if not settings.DATALAKE_BUCKET:
        return {}
    try:
        obj = _s3.get_object(Bucket=settings.DATALAKE_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception as exc:  # noqa: BLE001
        log.info("previsão '%s' indisponível: %s", key, exc)
        return {}


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


async def _safe(name: str, fn: Callable[[], str]) -> list[dict[str, Any]]:
    """Roda uma query em thread; nunca derruba o dashboard inteiro por uma falha."""
    try:
        return await asyncio.to_thread(run_query, fn())
    except Exception as exc:  # noqa: BLE001
        log.warning("indicador '%s' falhou: %s", name, exc)
        return []


async def _safe_batch(name: str, mart_fn: Callable[[], str], raw_fn: Callable[[], str]) -> list[dict[str, Any]]:
    """BATCH layer com fallback: tenta o mart Parquet; se a tabela ainda não
    existe (ex.: antes do 1º job Glue), cai no equivalente sobre o cru."""
    if not settings.MARTS_ENABLED:
        return await _safe(name, raw_fn)
    try:
        return await asyncio.to_thread(run_query, mart_fn())
    except Exception as exc:  # noqa: BLE001
        log.info("mart '%s' indisponível (%s) — fallback no cru", name, exc)
        return await _safe(name + ":raw", raw_fn)


def _merge_volume(batch_rows: list[dict], speed_rows: list[dict]) -> dict[str, Any]:
    """Reconciliação Lambda: histórico (mart horário) + hora corrente (speed)."""
    merged: dict[str, int] = {}
    for r in batch_rows:
        merged[str(r["bucket"])] = int(r["orders"])
    for r in speed_rows:  # a hora corrente sobrescreve qualquer resíduo
        merged[str(r["bucket"])] = int(r["orders"])
    buckets = sorted(merged.keys())
    return {"x": buckets, "y": [merged[b] for b in buckets]}


def _shape_kpis(batch_kpi_rows, last_hour_rows, courier_rows, open_rows) -> dict[str, Any]:
    k = batch_kpi_rows[0] if batch_kpi_rows else {}
    lh = last_hour_rows[0] if last_hour_rows else {}
    c = courier_rows[0] if courier_rows else {}
    open_orders = sum(int(r.get("orders") or 0) for r in open_rows)
    avg_min = k.get("avg_delivery_min")
    return {
        "total_orders": int(k.get("total_orders") or 0),
        "orders_last_hour": int(lh.get("orders_last_hour") or 0),
        "delivered_orders": int(k.get("delivered_orders") or 0),
        "avg_delivery_min": round(float(avg_min), 1) if avg_min is not None else None,
        "active_couriers": int(c.get("active") or 0),
        "available_couriers": int(c.get("available") or 0),
        "busy_couriers": int(c.get("busy") or 0),
        "open_orders": open_orders,
    }


@app.get("/dashboard/api/data")
async def dashboard_data():
    (
        kpi_rows, volume_batch, state_times, regions, heatmap, top_rest, hist,
        volume_speed, last_hour, open_states, couriers,
    ) = await asyncio.gather(
        # ── BATCH layer (marts Parquet, com fallback no cru) ──
        _safe_batch("kpis", Q.mart_kpis, Q.raw_kpis),
        _safe_batch("volume", Q.mart_volume, Q.raw_volume),
        _safe_batch("state_times", Q.mart_state_times, Q.raw_state_times),
        _safe_batch("regions", Q.mart_regions, Q.raw_regions),
        _safe_batch("heatmap", Q.mart_heatmap, Q.raw_heatmap),
        _safe_batch("top_restaurants", Q.mart_top_restaurants, Q.raw_top_restaurants),
        _safe_batch("delivery_hist", Q.mart_delivery_hist, Q.raw_delivery_hist),
        # ── SPEED layer (cru, janela curta) ──
        _safe("volume_speed", Q.speed_volume),
        _safe("orders_last_hour", Q.speed_orders_last_hour),
        _safe("open_states", Q.speed_open_orders_by_state),
        _safe("couriers", Q.speed_active_couriers),
    )

    volume_out = _merge_volume(volume_batch, volume_speed)

    state_times_out = {
        "labels": [Q.STATE_NAMES.get(int(r["id_state"]), f"Estado {r['id_state']}") for r in state_times],
        "minutes": [round(float(r["avg_seconds"]) / 60.0, 2) if r.get("avg_seconds") is not None else 0 for r in state_times],
    }

    regions_out = {
        "labels": [str(r["region"]) for r in regions],
        "orders": [int(r["orders"]) for r in regions],
    }

    z = [[0 for _ in range(24)] for _ in range(7)]
    for r in heatmap:
        dow = int(r["dow"])  # 1=Seg .. 7=Dom
        hr = int(r["hr"])
        if 1 <= dow <= 7 and 0 <= hr <= 23:
            z[dow - 1][hr] = int(r["orders"])
    heatmap_out = {
        "z": z,
        "dow": [Q.WEEKDAY_NAMES[d] for d in range(1, 8)],
        "hours": list(range(24)),
    }

    top_out = {
        "labels": [str(r["name"]) for r in top_rest],
        "orders": [int(r["orders"]) for r in top_rest],
    }

    hist_out = {
        "bins": [int(r["bin_min"]) for r in hist],
        "orders": [int(r["orders"]) for r in hist],
    }

    open_out = {
        "labels": [Q.STATE_NAMES.get(int(r["id_state"]), f"Estado {r['id_state']}") for r in open_states],
        "orders": [int(r["orders"]) for r in open_states],
    }

    return JSONResponse({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "speed_lookback_days": settings.SPEED_LOOKBACK_DAYS,
        "courier_window_min": settings.COURIER_WINDOW_MIN,
        "kpis": _shape_kpis(kpi_rows, last_hour, couriers, open_states),
        "volume": volume_out,
        "state_times": state_times_out,
        "regions": regions_out,
        "heatmap": heatmap_out,
        "top_restaurants": top_out,
        "delivery_hist": hist_out,
        "open_states": open_out,
    })


@app.get("/dashboard/api/demand")
async def dashboard_demand():
    return JSONResponse(await asyncio.to_thread(_read_pred_json, "predictions/demand/latest.json"))


@app.get("/dashboard/api/anomalies")
async def dashboard_anomalies():
    return JSONResponse(await asyncio.to_thread(_read_pred_json, "predictions/anomalies/latest.json"))


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("__ASSISTANT_URL__", settings.ASSISTANT_URL)
    return HTMLResponse(html)
