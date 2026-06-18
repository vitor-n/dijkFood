"""
Modelo de ETA (tempo de entrega no momento do pedido).

Ciclo de vida tratado explicitamente (requisito do Objetivo 3):
  - Coleta:     features.eta_training_data() via Athena (camada analítica).
  - Treino:     RandomForestRegressor + target-encoding de restaurante/região.
  - Implantação: artefato joblib persistido no S3 (models/eta/model.joblib),
                 servido em memória pelo prediction-service (ECS) e
                 recarregável (a pipeline SageMaker pode republicar o artefato).
  - Serving:    predição síncrona com fallback determinístico (nunca falha).
"""
from __future__ import annotations

import io
import json
import logging
import math
import threading
from datetime import datetime, timezone
from typing import Any

import boto3
import joblib
import numpy as np

from . import features as F
from .athena import run_query
from .config import settings

log = logging.getLogger("prediction.model")

_s3 = boto3.client("s3", region_name=settings.AWS_REGION)

FEATURE_ORDER = [
    "hour_sin", "hour_cos", "dow", "is_weekend",
    "rest_mean", "rest_log_count", "region_mean",
]

_MODEL_KEY = f"{settings.MODEL_PREFIX}/model.joblib"
_META_KEY = f"{settings.MODEL_PREFIX}/metadata.json"


def _feature_row(hr: int, dow: int, rest_mean: float, rest_count: float, region_mean: float) -> list[float]:
    return [
        math.sin(2 * math.pi * hr / 24.0),
        math.cos(2 * math.pi * hr / 24.0),
        float(dow),
        1.0 if dow in (6, 7) else 0.0,
        float(rest_mean),
        math.log1p(float(rest_count)),
        float(region_mean),
    ]


class ETAModel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bundle: dict[str, Any] | None = None

    # ── Serving ───────────────────────────────────────────────────────────────
    @property
    def is_ready(self) -> bool:
        return self.bundle is not None and self.bundle.get("model") is not None

    def predict(self, id_restaurant: int | None, hr: int, dow: int) -> dict[str, Any]:
        b = self.bundle
        if not b:
            return {"eta_minutes": round(settings.ETA_FALLBACK_MIN, 1), "source": "fallback_constant"}

        global_mean = b["global_mean"]
        rest_stats = b["rest_stats"]
        region_stats = b["region_stats"]

        rs = rest_stats.get(str(id_restaurant)) if id_restaurant is not None else None
        if rs:
            rest_mean, rest_count = rs[0], rs[1]
        else:
            rest_mean, rest_count = global_mean, 0
        # região do restaurante (se conhecida)
        region = b["rest_region"].get(str(id_restaurant)) if id_restaurant is not None else None
        region_mean = region_stats.get(str(region), global_mean) if region is not None else global_mean

        model = b.get("model")
        if model is None:
            est = rest_mean if rest_count > 0 else region_mean
            return {"eta_minutes": round(float(est), 1), "source": "history"}

        x = np.array([_feature_row(hr, dow, rest_mean, rest_count, region_mean)], dtype=float)
        pred = float(model.predict(x)[0])
        pred = max(1.0, min(pred, 360.0))
        return {
            "eta_minutes": round(pred, 1),
            "source": "model",
            "model_trained_at": b.get("trained_at"),
        }

    # ── Persistência S3 ───────────────────────────────────────────────────────
    def load_from_s3(self) -> bool:
        if not settings.DATALAKE_BUCKET:
            return False
        try:
            obj = _s3.get_object(Bucket=settings.DATALAKE_BUCKET, Key=_MODEL_KEY)
            bundle = joblib.load(io.BytesIO(obj["Body"].read()))
            with self._lock:
                self.bundle = bundle
            log.info("Modelo ETA carregado do S3 (trained_at=%s)", bundle.get("trained_at"))
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("Sem modelo no S3 (%s)", exc)
            return False

    def _save_to_s3(self, bundle: dict[str, Any]) -> None:
        if not settings.DATALAKE_BUCKET:
            log.warning("DATALAKE_BUCKET não definido — modelo não persistido")
            return
        buf = io.BytesIO()
        joblib.dump(bundle, buf)
        buf.seek(0)
        _s3.put_object(Bucket=settings.DATALAKE_BUCKET, Key=_MODEL_KEY, Body=buf.getvalue())
        meta = {k: bundle[k] for k in ("trained_at", "metrics", "source") if k in bundle}
        _s3.put_object(
            Bucket=settings.DATALAKE_BUCKET, Key=_META_KEY,
            Body=json.dumps(meta, default=str).encode("utf-8"),
            ContentType="application/json",
        )

    # ── Treino ────────────────────────────────────────────────────────────────
    def train(self, source: str = "in-container") -> dict[str, Any]:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.metrics import mean_absolute_error
        from sklearn.model_selection import train_test_split

        rows = run_query(F.eta_training_data())
        rows = [r for r in rows if r.get("minutes") is not None]
        n = len(rows)
        if n < settings.MIN_TRAIN_SAMPLES:
            raise ValueError(f"Amostras insuficientes para treino: {n} < {settings.MIN_TRAIN_SAMPLES}")

        minutes = np.array([float(r["minutes"]) for r in rows])
        global_mean = float(minutes.mean())

        # Target encoding (estatísticas históricas) — também servem de fallback.
        rest_sum: dict[str, float] = {}
        rest_cnt: dict[str, int] = {}
        rest_region: dict[str, int] = {}
        region_sum: dict[str, float] = {}
        region_cnt: dict[str, int] = {}
        for r in rows:
            rid = str(r.get("id_restaurant"))
            reg = str(r.get("region"))
            m = float(r["minutes"])
            rest_sum[rid] = rest_sum.get(rid, 0.0) + m
            rest_cnt[rid] = rest_cnt.get(rid, 0) + 1
            rest_region[rid] = int(r.get("region")) if r.get("region") is not None else -1
            region_sum[reg] = region_sum.get(reg, 0.0) + m
            region_cnt[reg] = region_cnt.get(reg, 0) + 1

        rest_stats = {k: (rest_sum[k] / rest_cnt[k], rest_cnt[k]) for k in rest_sum}
        region_stats = {k: region_sum[k] / region_cnt[k] for k in region_sum}

        X = np.array([
            _feature_row(
                int(r["hr"]), int(r["dow"]),
                rest_stats[str(r["id_restaurant"])][0], rest_stats[str(r["id_restaurant"])][1],
                region_stats[str(r["region"])],
            )
            for r in rows
        ], dtype=float)
        y = minutes

        if n >= 80:
            X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
        else:
            X_tr, X_te, y_tr, y_te = X, X, y, y

        model = RandomForestRegressor(
            n_estimators=160, max_depth=12, min_samples_leaf=3,
            n_jobs=-1, random_state=42,
        )
        model.fit(X_tr, y_tr)
        holdout_mae = float(mean_absolute_error(y_te, model.predict(X_te)))
        baseline_mae = float(mean_absolute_error(y_te, np.full_like(y_te, global_mean)))

        bundle = {
            "model": model,
            "global_mean": global_mean,
            "rest_stats": rest_stats,
            "region_stats": region_stats,
            "rest_region": rest_region,
            "feature_order": FEATURE_ORDER,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "metrics": {
                "n_samples": n,
                "holdout_mae_min": round(holdout_mae, 2),
                "baseline_mae_min": round(baseline_mae, 2),
                "improvement_pct": round(100 * (baseline_mae - holdout_mae) / baseline_mae, 1) if baseline_mae else 0.0,
            },
        }
        with self._lock:
            self.bundle = bundle
        self._save_to_s3(bundle)
        log.info("Modelo ETA treinado: %s", bundle["metrics"])
        return bundle["metrics"]

    def info(self) -> dict[str, Any]:
        b = self.bundle
        if not b:
            return {"ready": False, "fallback_minutes": settings.ETA_FALLBACK_MIN}
        return {
            "ready": True,
            "trained_at": b.get("trained_at"),
            "source": b.get("source"),
            "metrics": b.get("metrics"),
            "n_restaurants": len(b.get("rest_stats", {})),
            "n_regions": len(b.get("region_stats", {})),
        }


eta_model = ETAModel()
