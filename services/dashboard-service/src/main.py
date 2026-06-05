"""
dashboard-service — camada analítica (batch/near-real-time) do DijkFood.

Renderiza os 6 indicadores obrigatórios + métricas de estado instantâneo da
operação, consultando o Athena por cima do S3 alimentado pelo Firehose.
A UI (Plotly) é servida estaticamente; os dados vêm de /dashboard/api/data.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from . import queries as Q
from .athena import run_query
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dashboard")

app = FastAPI(title="DijkFood · Dashboard Analítico")

_STATIC = Path(__file__).parent / "static"


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


def _shape_kpis(kpi_rows, courier_rows, open_rows) -> dict[str, Any]:
    k = kpi_rows[0] if kpi_rows else {}
    c = courier_rows[0] if courier_rows else {}
    open_orders = sum(int(r.get("orders") or 0) for r in open_rows)
    avg_min = k.get("avg_delivery_min")
    return {
        "total_orders": int(k.get("total_orders") or 0),
        "orders_last_hour": int(k.get("orders_last_hour") or 0),
        "delivered_orders": int(k.get("delivered_orders") or 0),
        "avg_delivery_min": round(float(avg_min), 1) if avg_min is not None else None,
        "unique_users": int(k.get("unique_users") or 0),
        "active_couriers": int(c.get("active") or 0),
        "available_couriers": int(c.get("available") or 0),
        "busy_couriers": int(c.get("busy") or 0),
        "open_orders": open_orders,
    }


@app.get("/dashboard/api/data")
async def dashboard_data():
    (
        volume, state_times, regions, heatmap, top_rest,
        hist, open_states, couriers, kpi_rows,
    ) = await asyncio.gather(
        _safe("volume", Q.volume_over_time),
        _safe("state_times", Q.avg_time_per_state),
        _safe("regions", Q.orders_by_region),
        _safe("heatmap", Q.demand_heatmap),
        _safe("top_restaurants", Q.top_restaurants),
        _safe("delivery_hist", Q.delivery_time_histogram),
        _safe("open_states", Q.open_orders_by_state),
        _safe("couriers", Q.active_couriers),
        _safe("kpis", Q.kpis),
    )

    # ── Volume no tempo ──
    volume_out = {
        "x": [r["bucket"] for r in volume],
        "y": [int(r["orders"]) for r in volume],
    }

    # ── Tempo médio por estado (em minutos) ──
    state_times_out = {
        "labels": [Q.STATE_NAMES.get(int(r["id_state"]), f"Estado {r['id_state']}") for r in state_times],
        "minutes": [round(float(r["avg_seconds"]) / 60.0, 2) if r.get("avg_seconds") is not None else 0 for r in state_times],
    }

    # ── Distribuição por região ──
    regions_out = {
        "labels": [str(r["region"]) for r in regions],
        "orders": [int(r["orders"]) for r in regions],
    }

    # ── Heatmap demanda (7 x 24) ──
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

    # ── Top 10 restaurantes ──
    top_out = {
        "labels": [str(r["name"]) for r in top_rest],
        "orders": [int(r["orders"]) for r in top_rest],
    }

    # ── Histograma do tempo de entrega ──
    hist_out = {
        "bins": [int(r["bin_min"]) for r in hist],
        "orders": [int(r["orders"]) for r in hist],
    }

    # ── Pedidos abertos por estado ──
    open_out = {
        "labels": [Q.STATE_NAMES.get(int(r["id_state"]), f"Estado {r['id_state']}") for r in open_states],
        "orders": [int(r["orders"]) for r in open_states],
    }

    return JSONResponse({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": settings.LOOKBACK_DAYS,
        "kpis": _shape_kpis(kpi_rows, couriers, open_states),
        "volume": volume_out,
        "state_times": state_times_out,
        "regions": regions_out,
        "heatmap": heatmap_out,
        "top_restaurants": top_out,
        "delivery_hist": hist_out,
        "open_states": open_out,
    })


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
async def dashboard_page():
    return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))
