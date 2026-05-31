"""Consultas Athena da camada preditiva (features de treino + monitoramento)."""
from .config import settings

T = f'"{settings.GLUE_DATABASE}"."{settings.EVENTS_TABLE}"'

# Dataset de treino: 1 linha por pedido concluído, com features + label (segundos).
TRAINING_FEATURES = f"""
WITH t AS (
  SELECT order_id,
    max(restaurant_id) AS restaurant_id,
    max(h3_cell) AS h3_cell,
    min(CASE WHEN event_type = 'order_created' THEN from_iso8601_timestamp(occurred_at) END) AS t0,
    max(CASE WHEN state_id = 6 THEN from_iso8601_timestamp(occurred_at) END) AS t6
  FROM {T}
  WHERE order_id IS NOT NULL
  GROUP BY order_id
)
SELECT restaurant_id, h3_cell,
       hour(t0) AS hr, day_of_week(t0) AS dow,
       date_diff('second', t0, t6) AS total_seconds
FROM t
WHERE t0 IS NOT NULL AND t6 IS NOT NULL AND t6 >= t0
"""

# Monitoramento: MAE entre o ETA previsto (gravado no order_created) e o real.
MONITORING_MAE = f"""
WITH t AS (
  SELECT order_id,
    max(predicted_eta_s) AS predicted,
    min(CASE WHEN event_type = 'order_created' THEN from_iso8601_timestamp(occurred_at) END) AS t0,
    max(CASE WHEN state_id = 6 THEN from_iso8601_timestamp(occurred_at) END) AS t6
  FROM {T}
  WHERE order_id IS NOT NULL
  GROUP BY order_id
)
SELECT count(*) AS n,
       round(avg(abs(predicted - date_diff('second', t0, t6))), 1) AS mae_seconds
FROM t
WHERE predicted IS NOT NULL AND t0 IS NOT NULL AND t6 IS NOT NULL AND t6 >= t0
"""
