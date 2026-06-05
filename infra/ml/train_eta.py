"""
train_eta.py — entrypoint de treino executado pelo SageMaker (container sklearn).

Faz parte da pipeline GERENCIADA (EventBridge → Step Functions → SageMaker):
coleta as features na camada analítica (Athena), treina o RandomForest do ETA e
grava o artefato em /opt/ml/model/model.joblib. O SageMaker empacota como
model.tar.gz no S3; a Lambda de callback "promove" o artefato para o local de
serving (models/eta/model.joblib), de onde o prediction-service (ECS) o carrega.

O bundle é byte-a-byte compatível com services/prediction-service/src/model.py.
"""
import io
import math
import os
import time
from datetime import datetime, timezone

import boto3
import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
GLUE_DATABASE = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "dijkfood-analytics")
LOOKBACK_DAYS = int(os.environ.get("TRAIN_LOOKBACK_DAYS", "60"))
MODEL_DIR = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")

FEATURE_ORDER = ["hour_sin", "hour_cos", "dow", "is_weekend", "rest_mean", "rest_log_count", "region_mean"]
_athena = boto3.client("athena", region_name=REGION)


def _run_query(sql):
    qid = _athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": GLUE_DATABASE},
        WorkGroup=ATHENA_WORKGROUP,
    )["QueryExecutionId"]
    while True:
        st = _athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] == "SUCCEEDED":
            break
        if st["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError("Athena: " + st.get("StateChangeReason", ""))
        time.sleep(1.5)
    rows, first = [], True
    for page in _athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        cols = [c["Name"] for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
        for r in page["ResultSet"]["Rows"][1 if first else 0:]:
            cells = r.get("Data", [])
            rows.append({cols[i]: (cells[i].get("VarCharValue") if i < len(cells) else None) for i in range(len(cols))})
        first = False
    return rows


def _sql():
    return f"""
WITH orders_created AS (
    SELECT dados.id_order AS id_order,
           from_iso8601_timestamp(event_timestamp) AS created_at,
           dados.id_restaurant AS id_restaurant
    FROM events WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
      AND from_iso8601_timestamp(event_timestamp) > now() - interval '{LOOKBACK_DAYS}' day
),
delivered AS (
    SELECT dados.id_order AS id_order, from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events WHERE entidade='Order' AND acao='UPDATE' AND dados.id_state=6 AND dados.id_order IS NOT NULL
      AND from_iso8601_timestamp(event_timestamp) > now() - interval '{LOOKBACK_DAYS}' day
),
restaurants AS (
    SELECT dados.id_restaurant AS id_restaurant, max(dados.h3_index) AS region
    FROM events WHERE entidade='Restaurant' AND dados.id_restaurant IS NOT NULL GROUP BY dados.id_restaurant
),
lifecycle AS (
    SELECT o.id_order, o.created_at, o.id_restaurant, coalesce(r.region,-1) AS region, min(d.changed_at) AS delivered_at
    FROM orders_created o JOIN delivered d ON o.id_order=d.id_order
    LEFT JOIN restaurants r ON o.id_restaurant=r.id_restaurant
    GROUP BY o.id_order, o.created_at, o.id_restaurant, r.region
)
SELECT id_restaurant, region, hour(created_at) AS hr, day_of_week(created_at) AS dow,
       date_diff('second', created_at, delivered_at)/60.0 AS minutes
FROM lifecycle WHERE delivered_at IS NOT NULL
  AND date_diff('second', created_at, delivered_at) BETWEEN 60 AND 21600
"""


def _feature_row(hr, dow, rest_mean, rest_count, region_mean):
    return [
        math.sin(2 * math.pi * hr / 24.0), math.cos(2 * math.pi * hr / 24.0),
        float(dow), 1.0 if dow in (6, 7) else 0.0,
        float(rest_mean), math.log1p(float(rest_count)), float(region_mean),
    ]


def main():
    rows = [r for r in _run_query(_sql()) if r.get("minutes") not in (None, "")]
    n = len(rows)
    if n < 40:
        raise SystemExit(f"Amostras insuficientes: {n}")

    minutes = np.array([float(r["minutes"]) for r in rows])
    global_mean = float(minutes.mean())

    rest_sum, rest_cnt, rest_region, region_sum, region_cnt = {}, {}, {}, {}, {}
    for r in rows:
        rid, reg, m = str(r["id_restaurant"]), str(r["region"]), float(r["minutes"])
        rest_sum[rid] = rest_sum.get(rid, 0.0) + m
        rest_cnt[rid] = rest_cnt.get(rid, 0) + 1
        rest_region[rid] = int(float(r["region"])) if r["region"] is not None else -1
        region_sum[reg] = region_sum.get(reg, 0.0) + m
        region_cnt[reg] = region_cnt.get(reg, 0) + 1

    rest_stats = {k: (rest_sum[k] / rest_cnt[k], rest_cnt[k]) for k in rest_sum}
    region_stats = {k: region_sum[k] / region_cnt[k] for k in region_sum}

    X = np.array([
        _feature_row(int(r["hr"]), int(r["dow"]),
                     rest_stats[str(r["id_restaurant"])][0], rest_stats[str(r["id_restaurant"])][1],
                     region_stats[str(r["region"])])
        for r in rows
    ], dtype=float)
    y = minutes

    if n >= 80:
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    else:
        X_tr, X_te, y_tr, y_te = X, X, y, y

    model = RandomForestRegressor(n_estimators=160, max_depth=12, min_samples_leaf=3, n_jobs=-1, random_state=42)
    model.fit(X_tr, y_tr)
    holdout = float(mean_absolute_error(y_te, model.predict(X_te)))
    baseline = float(mean_absolute_error(y_te, np.full_like(y_te, global_mean)))

    bundle = {
        "model": model, "global_mean": global_mean, "rest_stats": rest_stats,
        "region_stats": region_stats, "rest_region": rest_region, "feature_order": FEATURE_ORDER,
        "trained_at": datetime.now(timezone.utc).isoformat(), "source": "sagemaker",
        "metrics": {
            "n_samples": n, "holdout_mae_min": round(holdout, 2), "baseline_mae_min": round(baseline, 2),
            "improvement_pct": round(100 * (baseline - holdout) / baseline, 1) if baseline else 0.0,
        },
    }
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(bundle, os.path.join(MODEL_DIR, "model.joblib"))
    print("ETA model trained:", bundle["metrics"])


if __name__ == "__main__":
    main()
