"""Testes de lógica pura da camada preditiva (sem AWS)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "prediction-service"))

from src import model, batch  # noqa: E402


def test_feature_row_shape():
    fr = model._feature_row(12, 3, 30.0, 5, 28.0)
    assert len(fr) == len(model.FEATURE_ORDER) == 7
    # weekend flag
    assert model._feature_row(0, 6, 0, 0, 0)[3] == 1.0
    assert model._feature_row(0, 3, 0, 0, 0)[3] == 0.0


def test_predict_fallback_without_bundle():
    m = model.ETAModel()
    r = m.predict(1, 12, 3)
    assert r["source"] == "fallback_constant" and r["eta_minutes"] > 0


def test_predict_history_when_model_none():
    m = model.ETAModel()
    m.bundle = {
        "global_mean": 30.0,
        "rest_stats": {"1": (25.0, 10)},
        "region_stats": {"100": 27.0},
        "rest_region": {"1": 100},
        "model": None,
    }
    r = m.predict(1, 12, 3)
    assert r["source"] == "history" and abs(r["eta_minutes"] - 25.0) < 0.01
    # restaurante desconhecido -> usa região/global
    r2 = m.predict(999, 12, 3)
    assert r2["eta_minutes"] > 0


def test_batch_parse_ts():
    dt = batch._parse_ts("2026-06-05 12:00:00.000")
    assert dt is not None and dt.tzinfo is not None
    assert batch._parse_ts("lixo") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  [ok] " + name)
    print("test_prediction OK")
