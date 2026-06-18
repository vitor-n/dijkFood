"""
SQL (Trino/Athena) dos indicadores do dashboard — Arquitetura Lambda.

Duas trilhas, conforme o padrão batch + speed:

  • BATCH  (`mart_*`)  — indicadores históricos pesados, lidos das tabelas Parquet
    pré-agregadas de hora em hora pelo Glue (build_marts.py). Varredura mínima:
    cada query lê alguns KB de Parquet em vez de varrer 30 dias de JSON cru.

  • SPEED  (`events`)  — indicadores "vivos" (pedidos abertos, entregadores
    ativos, volume da hora corrente), lidos da tabela crua numa janela CURTA
    (SPEED_LOOKBACK_DAYS). Reflete o que o Firehose acabou de despachar.

O "Volume de pedidos no tempo" é a RECONCILIAÇÃO batch+speed: histórico vem do
mart horário (buckets < hora corrente) e a hora corrente vem do speed — o
merge é feito no main.py.

Se os marts ainda não existirem (1ª execução, antes do 1º job Glue), o main.py
cai automaticamente nas funções `*_raw` equivalentes (fallback sobre o cru).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import settings

# Nomes dos estados (alinhado ao OrderState do banco / simulador)
STATE_NAMES = {
    1: "Confirmado",
    2: "Preparando",
    3: "Pronto p/ retirada",
    4: "Retirado",
    5: "Em trânsito",
    6: "Entregue",
}

WEEKDAY_NAMES = {
    1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb", 7: "Dom",
}


# ──────────────────────────────────────────────────────────────────────────────
# BATCH layer — lê os marts Parquet (rápido). Sem filtro temporal: os marts já
# consolidam o histórico relevante e são minúsculos.
# ──────────────────────────────────────────────────────────────────────────────
def mart_kpis() -> str:
    return "SELECT total_orders, delivered_orders, avg_delivery_min FROM mart_kpis"


def mart_volume() -> str:
    # Histórico ANTERIOR à janela da speed layer; a janela recente (completa) vem
    # do cru. Sem overlap (à prova de gap mesmo se o job Glue atrasar).
    n = settings.SPEED_LOOKBACK_DAYS
    return f"""
    SELECT bucket, orders FROM mart_hourly_volume
    WHERE bucket < date_trunc('hour', now() - interval '{n}' day)
    ORDER BY bucket
    """


def mart_state_times() -> str:
    return "SELECT id_state, avg_seconds, samples FROM mart_state_avg_seconds ORDER BY id_state"


def mart_regions() -> str:
    return ("SELECT CAST(region AS varchar) AS region, orders FROM mart_region_distribution "
            "WHERE region IS NOT NULL ORDER BY orders DESC LIMIT 25")


def mart_heatmap() -> str:
    return "SELECT dow, hr, orders FROM mart_demand_heatmap"


def mart_top_restaurants() -> str:
    return ("SELECT id_restaurant, coalesce(name, concat('Restaurante #', CAST(id_restaurant AS varchar))) AS name, "
            "orders FROM mart_top_restaurants ORDER BY orders DESC LIMIT 10")


def mart_delivery_hist() -> str:
    return "SELECT bin_min, orders FROM mart_delivery_histogram ORDER BY bin_min"


# ──────────────────────────────────────────────────────────────────────────────
# SPEED layer — lê a tabela crua `events` numa janela CURTA (near-real-time).
# ──────────────────────────────────────────────────────────────────────────────
def _partition_filter(lookback_days: int) -> str:
    now = datetime.now(timezone.utc)
    dates = set()
    # Buffer de +/- 1 dia para tolerar fuso/limite de partição.
    for i in range(-1, lookback_days + 2):
        d = now - timedelta(days=i)
        dates.add((d.strftime("%Y"), d.strftime("%m"), d.strftime("%d")))
    clauses = [f"(year = '{y}' AND month = '{m}' AND day = '{d}')" for y, m, d in sorted(dates)]
    return f"({' OR '.join(clauses)})"


def _speed_window() -> str:
    return f"now() - interval '{settings.SPEED_LOOKBACK_DAYS}' day"


def speed_volume() -> str:
    """Volume por hora na janela recente (completa, do cru) — overlay de tempo
    real do merge Lambda. Cobre exatamente [now - SPEED_LOOKBACK_DAYS, now]; o
    histórico anterior vem do mart horário."""
    n = settings.SPEED_LOOKBACK_DAYS
    pf = _partition_filter(n)
    return f"""
    SELECT date_trunc('hour', from_iso8601_timestamp(event_timestamp)) AS bucket,
           count(*) AS orders
    FROM events
    WHERE entidade = 'Order' AND acao = 'CREATE' AND dados.id_order IS NOT NULL
      AND {pf}
      AND from_iso8601_timestamp(event_timestamp) >= date_trunc('hour', now() - interval '{n}' day)
    GROUP BY 1 ORDER BY 1
    """


def speed_orders_last_hour() -> str:
    pf = _partition_filter(settings.SPEED_LOOKBACK_DAYS)
    return f"""
    SELECT count(*) AS orders_last_hour
    FROM events
    WHERE entidade = 'Order' AND acao = 'CREATE' AND dados.id_order IS NOT NULL
      AND {pf}
      AND from_iso8601_timestamp(event_timestamp) > now() - interval '1' hour
    """


def speed_open_orders_by_state() -> str:
    """Pedidos ainda abertos (último estado < 6), por estado — janela curta."""
    pf = _partition_filter(settings.SPEED_LOOKBACK_DAYS)
    return f"""
    WITH transitions AS (
        SELECT dados.id_order AS id_order, 1 AS id_state,
               from_iso8601_timestamp(event_timestamp) AS changed_at
        FROM events
        WHERE entidade = 'Order' AND acao = 'CREATE' AND dados.id_order IS NOT NULL
          AND {pf} AND from_iso8601_timestamp(event_timestamp) > {_speed_window()}
        UNION ALL
        SELECT dados.id_order AS id_order, dados.id_state AS id_state,
               from_iso8601_timestamp(event_timestamp) AS changed_at
        FROM events
        WHERE entidade = 'Order' AND acao = 'UPDATE' AND dados.id_order IS NOT NULL
          AND {pf} AND from_iso8601_timestamp(event_timestamp) > {_speed_window()}
    ), ranked AS (
        SELECT id_order, id_state,
               row_number() OVER (PARTITION BY id_order ORDER BY changed_at DESC) AS rn
        FROM transitions
    )
    SELECT id_state, count(*) AS orders
    FROM ranked WHERE rn = 1 AND id_state < 6
    GROUP BY id_state ORDER BY id_state
    """


def speed_active_couriers() -> str:
    """Entregadores que reportaram posição na janela COURIER_WINDOW_MIN."""
    pf = _partition_filter(1)
    win = settings.COURIER_WINDOW_MIN
    return f"""
    WITH latest AS (
        SELECT dados.id_courier AS id_courier,
               dados.status     AS status,
               from_iso8601_timestamp(event_timestamp) AS ts,
               row_number() OVER (PARTITION BY dados.id_courier
                                  ORDER BY from_iso8601_timestamp(event_timestamp) DESC) AS rn
        FROM events
        WHERE entidade = 'Position' AND dados.id_courier IS NOT NULL
          AND {pf}
          AND from_iso8601_timestamp(event_timestamp) > now() - interval '{win}' minute
    )
    SELECT
        count(*)                       AS active,
        count_if(status = 'AVAILABLE') AS available,
        count_if(status = 'BUSY')      AS busy
    FROM latest WHERE rn = 1
    """


# ──────────────────────────────────────────────────────────────────────────────
# FALLBACK cru — usado só quando os marts ainda não foram materializados.
# Varre a tabela crua na janela LOOKBACK_DAYS (mais lento; transitório).
# ──────────────────────────────────────────────────────────────────────────────
def _raw_base_ctes() -> str:
    pf = _partition_filter(settings.LOOKBACK_DAYS)
    lb = f"now() - interval '{settings.LOOKBACK_DAYS}' day"
    return f"""
WITH orders_created AS (
    SELECT dados.id_order AS id_order,
           from_iso8601_timestamp(event_timestamp) AS created_at,
           dados.id_restaurant AS id_restaurant, dados.id_user AS id_user
    FROM events
    WHERE entidade = 'Order' AND acao = 'CREATE' AND dados.id_order IS NOT NULL
      AND {pf} AND from_iso8601_timestamp(event_timestamp) > {lb}
),
transitions AS (
    SELECT dados.id_order AS id_order, 1 AS id_state,
           from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events
    WHERE entidade = 'Order' AND acao = 'CREATE' AND dados.id_order IS NOT NULL
      AND {pf} AND from_iso8601_timestamp(event_timestamp) > {lb}
    UNION ALL
    SELECT dados.id_order AS id_order, dados.id_state AS id_state,
           from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events
    WHERE entidade = 'Order' AND acao = 'UPDATE' AND dados.id_order IS NOT NULL
      AND {pf} AND from_iso8601_timestamp(event_timestamp) > {lb}
),
restaurants AS (
    SELECT dados.id_restaurant AS id_restaurant,
           max(dados.name) AS name, max(dados.h3_index) AS h3_index
    FROM events
    WHERE entidade = 'Restaurant' AND dados.id_restaurant IS NOT NULL AND {pf}
    GROUP BY dados.id_restaurant
)
"""


def raw_kpis() -> str:
    return _raw_base_ctes() + """
    , lifecycle AS (
        SELECT o.id_order, o.created_at,
               min(CASE WHEN t.id_state = 6 THEN t.changed_at END) AS delivered_at
        FROM orders_created o JOIN transitions t ON o.id_order = t.id_order
        GROUP BY o.id_order, o.created_at
    )
    SELECT
        (SELECT count(*) FROM orders_created)                              AS total_orders,
        (SELECT count(*) FROM lifecycle WHERE delivered_at IS NOT NULL)    AS delivered_orders,
        (SELECT avg(date_diff('second', created_at, delivered_at)) / 60.0
            FROM lifecycle WHERE delivered_at IS NOT NULL)                 AS avg_delivery_min
    """


def raw_volume() -> str:
    return _raw_base_ctes() + """
    SELECT date_trunc('hour', created_at) AS bucket, count(*) AS orders
    FROM orders_created GROUP BY 1 ORDER BY 1
    """


def raw_state_times() -> str:
    return _raw_base_ctes() + """
    , seq AS (
        SELECT id_state, changed_at,
               lead(changed_at) OVER (PARTITION BY id_order ORDER BY changed_at) AS next_at
        FROM transitions
    )
    SELECT id_state, avg(date_diff('second', changed_at, next_at)) AS avg_seconds, count(*) AS samples
    FROM seq WHERE next_at IS NOT NULL GROUP BY id_state ORDER BY id_state
    """


def raw_regions() -> str:
    return _raw_base_ctes() + """
    SELECT CAST(r.h3_index AS varchar) AS region, count(*) AS orders
    FROM orders_created o JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    WHERE r.h3_index IS NOT NULL
    GROUP BY r.h3_index ORDER BY orders DESC LIMIT 25
    """


def raw_heatmap() -> str:
    return _raw_base_ctes() + """
    SELECT day_of_week(created_at) AS dow, hour(created_at) AS hr, count(*) AS orders
    FROM orders_created GROUP BY 1, 2
    """


def raw_top_restaurants() -> str:
    return _raw_base_ctes() + """
    SELECT o.id_restaurant AS id_restaurant,
           coalesce(max(r.name), concat('Restaurante #', CAST(o.id_restaurant AS varchar))) AS name,
           count(*) AS orders
    FROM orders_created o LEFT JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    GROUP BY o.id_restaurant ORDER BY orders DESC LIMIT 10
    """


def raw_delivery_hist() -> str:
    return _raw_base_ctes() + """
    , lifecycle AS (
        SELECT o.id_order, o.created_at,
               min(CASE WHEN t.id_state = 6 THEN t.changed_at END) AS delivered_at
        FROM orders_created o JOIN transitions t ON o.id_order = t.id_order
        GROUP BY o.id_order, o.created_at
    )
    SELECT CAST(floor(date_diff('second', created_at, delivered_at) / 300.0) * 5 AS integer) AS bin_min,
           count(*) AS orders
    FROM lifecycle
    WHERE delivered_at IS NOT NULL
      AND date_diff('second', created_at, delivered_at) BETWEEN 0 AND 21600
    GROUP BY 1 ORDER BY 1
    """
