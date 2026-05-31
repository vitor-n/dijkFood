"""
Modelo de predição do tempo de entrega (Objetivo 3 — capacidade preditiva).

Ciclo de vida explícito:
  • Coleta   — eventos no data lake (Firehose → S3 Parquet).
  • Treino   — features via Athena → HistGradientBoostingRegressor.
  • Deploy   — modelo serializado (joblib) no S3; o serviço carrega no startup.
  • Monitor  — MAE entre previsto e real de pedidos concluídos (ver /predict/metrics).

Serving roda no ECS (não depende de endpoint SageMaker) e responde com timeout
curto; o order-service tem fallback heurístico, então a predição nunca regride
o SLA de criação de pedido.
"""
from __future__ import annotations

import hashlib
import io
import logging
import tarfile  # noqa: F401  (compat futura com artefatos SageMaker)
from dataclasses import dataclass

import boto3
import joblib
import numpy as np

from .config import settings

log = logging.getLogger("prediction-model")

H3_BUCKETS = 4096
FEATURE_NAMES = ["hour", "dow", "restaurant_id", "h3_bucket"]


def h3_to_bucket(h3_cell: str | None) -> int:
    if not h3_cell:
        return 0
    digest = hashlib.md5(h3_cell.encode("utf-8")).hexdigest()
    return int(digest, 16) % H3_BUCKETS


def featurize(hour: int, dow: int, restaurant_id: int | None, h3_cell: str | None) -> list[float]:
    return [
        float(hour),
        float(dow),
        float(restaurant_id or 0),
        float(h3_to_bucket(h3_cell)),
    ]


@dataclass
class TrainResult:
    samples: int
    trained: bool
    metric_mae: float | None = None
    note: str = ""


class _MeanModel:
    """Fallback determinístico quando há poucos dados para um modelo de fato."""

    def __init__(self, mean: float):
        self.mean = float(mean)

    def predict(self, X):  # noqa: N803
        return np.full((len(X),), self.mean, dtype=float)


class DeliveryTimeModel:
    def __init__(self):
        self._model = None
        self._s3 = boto3.client("s3", region_name=settings.AWS_REGION)

    @property
    def ready(self) -> bool:
        return self._model is not None

    # ── persistência (S3) ────────────────────────────────────────────────
    def load_from_s3(self) -> bool:
        if not settings.MODEL_BUCKET:
            return False
        try:
            obj = self._s3.get_object(Bucket=settings.MODEL_BUCKET, Key=settings.MODEL_KEY)
            self._model = joblib.load(io.BytesIO(obj["Body"].read()))
            log.info("Modelo carregado de s3://%s/%s", settings.MODEL_BUCKET, settings.MODEL_KEY)
            return True
        except Exception as exc:
            log.warning("Nenhum modelo carregado do S3: %s", exc)
            return False

    def save_to_s3(self) -> None:
        if not settings.MODEL_BUCKET or self._model is None:
            return
        buf = io.BytesIO()
        joblib.dump(self._model, buf)
        buf.seek(0)
        self._s3.put_object(Bucket=settings.MODEL_BUCKET, Key=settings.MODEL_KEY, Body=buf.getvalue())
        log.info("Modelo salvo em s3://%s/%s", settings.MODEL_BUCKET, settings.MODEL_KEY)

    # ── treino ───────────────────────────────────────────────────────────
    def train(self, rows: list[dict]) -> TrainResult:
        X, y = [], []
        for r in rows:
            try:
                secs = float(r["total_seconds"])
                if secs <= 0 or secs > 24 * 3600:
                    continue
                X.append(featurize(int(r["hr"]), int(r["dow"]),
                                   int(r["restaurant_id"]) if r.get("restaurant_id") else None,
                                   r.get("h3_cell")))
                y.append(secs)
            except (TypeError, ValueError):
                continue

        n = len(y)
        if n == 0:
            return TrainResult(samples=0, trained=False, note="sem dados de treino")

        if n < settings.MIN_TRAIN_SAMPLES:
            self._model = _MeanModel(float(np.mean(y)))
            self.save_to_s3()
            return TrainResult(samples=n, trained=True, note="poucos dados → modelo de média")

        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_absolute_error

        Xa, ya = np.array(X, dtype=float), np.array(y, dtype=float)
        X_tr, X_te, y_tr, y_te = train_test_split(Xa, ya, test_size=0.2, random_state=42)
        model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, max_depth=6)
        model.fit(X_tr, y_tr)
        mae = float(mean_absolute_error(y_te, model.predict(X_te)))

        self._model = model
        self.save_to_s3()
        return TrainResult(samples=n, trained=True, metric_mae=round(mae, 1),
                           note="HistGradientBoostingRegressor")

    # ── predição ─────────────────────────────────────────────────────────
    def predict_seconds(self, hour: int, dow: int, restaurant_id: int | None,
                         h3_cell: str | None) -> float | None:
        if self._model is None:
            return None
        feats = np.array([featurize(hour, dow, restaurant_id, h3_cell)], dtype=float)
        return float(self._model.predict(feats)[0])
