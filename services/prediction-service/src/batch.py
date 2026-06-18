"""
Camada preditiva — batch (demanda por região/horário + detecção de anomalias).

Espelha o ramo "Batch Transform → S3 previsões" da arquitetura: agrega o
histórico da camada analítica (Athena) e materializa as previsões em S3, de onde
o dashboard, a camada conversacional e os alertas podem consumir.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import numpy as np

from . import features as F
from .athena import run_query
from .config import settings

log = logging.getLogger("prediction.batch")
_s3 = boto3.client("s3", region_name=settings.AWS_REGION)

_DEMAND_KEY = f"{settings.PRED_PREFIX}/demand/latest.json"
_ANOM_KEY = f"{settings.PRED_PREFIX}/anomalies/latest.json"


def _put_json(key: str, payload: dict[str, Any]) -> None:
    if not settings.DATALAKE_BUCKET:
        log.warning("DATALAKE_BUCKET não definido — previsão não persistida")
        return
    body = json.dumps(payload, default=str).encode("utf-8")
    _s3.put_object(Bucket=settings.DATALAKE_BUCKET, Key=key, Body=body, ContentType="application/json")
    stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
    archive = key.replace("latest.json", f"{stamp}.json")
    _s3.put_object(Bucket=settings.DATALAKE_BUCKET, Key=archive, Body=body, ContentType="application/json")


def _get_json(key: str) -> dict[str, Any] | None:
    if not settings.DATALAKE_BUCKET:
        return None
    try:
        obj = _s3.get_object(Bucket=settings.DATALAKE_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:  # noqa: BLE001
        return None


# ── Demanda por região × horário (forecast seasonal-naive) ────────────────────
def forecast_demand() -> dict[str, Any]:
    rows = run_query(F.demand_history())
    # expected[region][dow][hr] = média de pedidos por dia observado naquele slot
    expected: dict[str, list[list[float]]] = {}
    for r in rows:
        reg = str(r["region"])
        dow = int(r["dow"])
        hr = int(r["hr"])
        days = max(1, int(r.get("days_observed") or 1))
        rate = float(r["orders"]) / days
        expected.setdefault(reg, [[0.0] * 24 for _ in range(8)])  # index 1..7
        expected[reg][dow][hr] = round(rate, 2)

    now = datetime.now(timezone.utc)
    next_24h = []
    for h in range(24):
        t = now + timedelta(hours=h)
        dow = t.isoweekday()  # 1=Mon..7=Sun (== Trino day_of_week)
        hr = t.hour
        total = sum(expected[reg][dow][hr] for reg in expected)
        per_region = sorted(
            ({"region": reg, "expected": expected[reg][dow][hr]} for reg in expected),
            key=lambda x: x["expected"], reverse=True,
        )[:5]
        next_24h.append({
            "ts": t.replace(minute=0, second=0, microsecond=0).isoformat(),
            "dow": dow, "hr": hr,
            "expected_total": round(total, 2),
            "top_regions": [p for p in per_region if p["expected"] > 0],
        })

    # perfil por região (total esperado/dia)
    region_profiles = sorted(
        ({"region": reg, "daily_expected": round(sum(sum(d) for d in mat), 2)}
         for reg, mat in expected.items()),
        key=lambda x: x["daily_expected"], reverse=True,
    )

    return {
        "generated_at": now.isoformat(),
        "model": "seasonal-naive (média por região × dia-da-semana × hora)",
        "lookback_days": settings.TRAIN_LOOKBACK_DAYS,
        "next_24h": next_24h,
        "region_profiles": region_profiles[:25],
    }


# ── Detecção de anomalias operacionais ────────────────────────────────────────
def detect_anomalies() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    anomalies: list[dict[str, Any]] = []

    # (a) Picos de demanda por região (z-score sobre a série horária)
    counts = run_query(F.hourly_counts())
    by_region: dict[str, list[dict[str, Any]]] = {}
    for r in counts:
        by_region.setdefault(str(r["region"]), []).append(r)

    recent_cutoff = now - timedelta(hours=48)
    for reg, series in by_region.items():
        vals = np.array([float(s["orders"]) for s in series])
        if len(vals) < settings.ANOMALY_MIN_BUCKETS:
            continue
        mu, sigma = float(vals.mean()), float(vals.std())
        if sigma <= 0:
            continue
        for s in series:
            bucket = s["bucket"]
            ts = _parse_ts(bucket)
            if ts is None or ts < recent_cutoff:
                continue
            z = (float(s["orders"]) - mu) / sigma
            if z >= 3.0 and float(s["orders"]) >= mu + 3:
                anomalies.append({
                    "type": "demand_spike",
                    "region": reg,
                    "at": _iso(bucket),
                    "value": int(s["orders"]),
                    "expected": round(mu, 1),
                    "zscore": round(z, 2),
                    "severity": "high" if z >= 5 else "medium",
                })

    # (b) Entregas anormalmente lentas (outliers de ETA por região via MAD)
    eta_rows = run_query(F.eta_training_data())
    by_reg_eta: dict[str, list[float]] = {}
    for r in eta_rows:
        if r.get("minutes") is not None:
            by_reg_eta.setdefault(str(r["region"]), []).append(float(r["minutes"]))
    for reg, mins in by_reg_eta.items():
        arr = np.array(mins)
        if len(arr) < 10:
            continue
        median = float(np.median(arr))
        mad = float(np.median(np.abs(arr - median))) or 1.0
        threshold = median + 3.5 * 1.4826 * mad
        slow = int((arr > threshold).sum())
        if slow > 0:
            anomalies.append({
                "type": "slow_deliveries",
                "region": reg,
                "count": slow,
                "median_min": round(median, 1),
                "threshold_min": round(threshold, 1),
                "severity": "high" if slow > 0.1 * len(arr) else "medium",
            })

    anomalies.sort(key=lambda a: 0 if a.get("severity") == "high" else 1)
    return {
        "generated_at": now.isoformat(),
        "method": "z-score (demanda) + MAD (ETA)",
        "count": len(anomalies),
        "anomalies": anomalies[:100],
    }


def _parse_ts(value: str):
    if not value:
        return None
    try:
        v = value.replace(" ", "T")
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: str) -> str:
    dt = _parse_ts(value)
    return dt.isoformat() if dt else str(value)


def run_and_store() -> dict[str, Any]:
    demand = forecast_demand()
    anomalies = detect_anomalies()
    _put_json(_DEMAND_KEY, demand)
    _put_json(_ANOM_KEY, anomalies)
    return {
        "demand_regions": len(demand.get("region_profiles", [])),
        "anomalies": anomalies.get("count", 0),
        "generated_at": demand["generated_at"],
    }


def read_demand() -> dict[str, Any]:
    return _get_json(_DEMAND_KEY) or {"generated_at": None, "next_24h": [], "region_profiles": []}


def read_anomalies() -> dict[str, Any]:
    return _get_json(_ANOM_KEY) or {"generated_at": None, "count": 0, "anomalies": []}
