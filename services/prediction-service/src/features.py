"""SQL de coleta (Athena) para treino do ETA e para o forecast de demanda/anomalias."""
from __future__ import annotations

from .config import settings


def _ctes() -> str:
    lb = settings.TRAIN_LOOKBACK_DAYS
    return f"""
WITH orders_created AS (
    SELECT dados.id_order AS id_order,
           from_iso8601_timestamp(event_timestamp) AS created_at,
           dados.id_restaurant AS id_restaurant
    FROM events
    WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
      AND from_iso8601_timestamp(event_timestamp) > now() - interval '{lb}' day
),
transitions AS (
    SELECT dados.id_order AS id_order, 6 AS id_state,
           from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events
    WHERE entidade='Order' AND acao='UPDATE' AND dados.id_state = 6 AND dados.id_order IS NOT NULL
      AND from_iso8601_timestamp(event_timestamp) > now() - interval '{lb}' day
),
restaurants AS (
    SELECT dados.id_restaurant AS id_restaurant, max(dados.h3_index) AS region
    FROM events WHERE entidade='Restaurant' AND dados.id_restaurant IS NOT NULL
    GROUP BY dados.id_restaurant
)
"""


def eta_training_data() -> str:
    """1 linha por pedido entregue, com features disponíveis no momento do pedido."""
    return _ctes() + """
    , lifecycle AS (
        SELECT o.id_order, o.created_at, o.id_restaurant,
               coalesce(r.region, -1) AS region,
               min(t.changed_at) AS delivered_at
        FROM orders_created o
        JOIN transitions t ON o.id_order = t.id_order
        LEFT JOIN restaurants r ON o.id_restaurant = r.id_restaurant
        GROUP BY o.id_order, o.created_at, o.id_restaurant, r.region
    )
    SELECT id_restaurant,
           region,
           hour(created_at)        AS hr,
           day_of_week(created_at) AS dow,
           date_diff('second', created_at, delivered_at) / 60.0 AS minutes
    FROM lifecycle
    WHERE delivered_at IS NOT NULL
      AND date_diff('second', created_at, delivered_at) BETWEEN """ + str(settings.MIN_DELIVERY_SECONDS) + """ AND 21600
    """


def demand_history() -> str:
    """Contagem de pedidos por região × dia-da-semana × hora (base do forecast)."""
    return _ctes() + """
    SELECT coalesce(r.region, -1) AS region,
           day_of_week(o.created_at) AS dow,
           hour(o.created_at) AS hr,
           count(*) AS orders,
           count(DISTINCT date(o.created_at)) AS days_observed
    FROM orders_created o
    LEFT JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    GROUP BY coalesce(r.region, -1), day_of_week(o.created_at), hour(o.created_at)
    """


def hourly_counts() -> str:
    """Série temporal de pedidos por região (base da detecção de picos de demanda).

    O bucket é configurável (ANOMALY_BUCKET_MINUTES): 60 min em produção; menor
    para demonstrar picos numa janela curta de simulação.
    """
    n = settings.ANOMALY_BUCKET_MINUTES
    if n == 60:
        bucket = "date_trunc('hour', o.created_at)"
    else:
        secs = n * 60
        bucket = f"from_unixtime(floor(to_unixtime(o.created_at) / {secs}) * {secs})"
    return _ctes() + f"""
    SELECT coalesce(r.region, -1) AS region,
           {bucket} AS bucket,
           count(*) AS orders
    FROM orders_created o
    LEFT JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    GROUP BY coalesce(r.region, -1), {bucket}
    """
