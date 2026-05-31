"""
Os 6 indicadores obrigatórios do dashboard analítico (Objetivo 3),
expressos em SQL Athena (Trino) sobre a tabela canônica de eventos `events`.

Como todos os eventos compartilham um schema flat, os indicadores são
computados diretamente da tabela raw (Parquet), sem precisar de uma curated
zone para a versão batch.
"""
from .config import settings

T = f'"{settings.GLUE_DATABASE}"."{settings.EVENTS_TABLE}"'

# 1) Volume de pedidos no tempo (por hora).
VOLUME_OVER_TIME = f"""
SELECT date_format(date_trunc('hour', from_iso8601_timestamp(occurred_at)), '%Y-%m-%d %H:00') AS bucket,
       count(*) AS n
FROM {T}
WHERE event_type = 'order_created'
GROUP BY 1
ORDER BY 1
"""

# 2) Tempo médio (s) em cada estado do ciclo de vida.
#    Diferença entre entrar no estado X e entrar no estado X+1 (LEAD por pedido).
AVG_TIME_PER_STATE = f"""
WITH ev AS (
  SELECT order_id, state_id, state_name,
         from_iso8601_timestamp(occurred_at) AS ts
  FROM {T}
  WHERE event_type IN ('order_created', 'order_state_changed')
    AND order_id IS NOT NULL AND state_id IS NOT NULL
),
seq AS (
  SELECT order_id, state_id, state_name, ts,
         lead(ts) OVER (PARTITION BY order_id ORDER BY state_id) AS next_ts
  FROM ev
)
SELECT state_id, state_name,
       round(avg(date_diff('second', ts, next_ts)), 1) AS avg_seconds
FROM seq
WHERE next_ts IS NOT NULL
GROUP BY state_id, state_name
ORDER BY state_id
"""

# 3) Distribuição de pedidos por região (célula H3).
ORDERS_BY_REGION = f"""
SELECT h3_cell, count(*) AS n
FROM {T}
WHERE event_type = 'order_created' AND h3_cell IS NOT NULL
GROUP BY h3_cell
ORDER BY n DESC
LIMIT 60
"""

# 4) Heatmap de demanda por hora x dia da semana (1=segunda ... 7=domingo).
DEMAND_HEATMAP = f"""
SELECT day_of_week(from_iso8601_timestamp(occurred_at)) AS dow,
       hour(from_iso8601_timestamp(occurred_at)) AS hr,
       count(*) AS n
FROM {T}
WHERE event_type = 'order_created'
GROUP BY 1, 2
ORDER BY 1, 2
"""

# 5) Top 10 restaurantes por volume.
TOP_RESTAURANTS = f"""
SELECT restaurant_id, count(*) AS n
FROM {T}
WHERE event_type = 'order_created' AND restaurant_id IS NOT NULL
GROUP BY restaurant_id
ORDER BY n DESC
LIMIT 10
"""

# 6) Histograma do tempo total de entrega (por minuto), do CONFIRMED ao DELIVERED.
DELIVERY_TIME_HISTOGRAM = f"""
WITH t AS (
  SELECT order_id,
    min(CASE WHEN event_type = 'order_created' THEN from_iso8601_timestamp(occurred_at) END) AS t0,
    max(CASE WHEN state_id = 6 THEN from_iso8601_timestamp(occurred_at) END) AS t6
  FROM {T}
  WHERE order_id IS NOT NULL
  GROUP BY order_id
)
SELECT cast(floor(date_diff('second', t0, t6) / 60.0) AS integer) AS minute_bucket,
       count(*) AS n
FROM t
WHERE t0 IS NOT NULL AND t6 IS NOT NULL AND t6 >= t0
GROUP BY 1
ORDER BY 1
"""

INDICATORS = {
    "volume_over_time": VOLUME_OVER_TIME,
    "avg_time_per_state": AVG_TIME_PER_STATE,
    "orders_by_region": ORDERS_BY_REGION,
    "demand_heatmap": DEMAND_HEATMAP,
    "top_restaurants": TOP_RESTAURANTS,
    "delivery_time_histogram": DELIVERY_TIME_HISTOGRAM,
}
