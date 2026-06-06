"""
SQL (Trino/Athena) dos indicadores do dashboard analítico.

Todas as consultas rodam sobre a tabela canônica `events` (Glue Catalog),
alimentada pelo Firehose. O filtro por `entidade` faz partition pruning; o
filtro temporal usa a janela de lookback configurável.

CTEs reaproveitadas:
  orders_created  — 1 linha por pedido criado
  transitions     — 1 linha por transição de estado (inclui CREATE => estado 1)
  restaurants     — cadastro de restaurantes (para nome e região/H3)
"""
from __future__ import annotations

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


def _partition_filter(lookback_days: int) -> str:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    dates = []
    # Generamos los días en el rango de búsqueda (con un buffer de +/- 1 día para zonas horarias)
    for i in range(-1, lookback_days + 2):
        d = now - timedelta(days=i)
        dates.append((d.strftime("%Y"), d.strftime("%m"), d.strftime("%d")))
    dates = sorted(list(set(dates)))
    clauses = [f"(year = '{y}' AND month = '{m}' AND day = '{d}')" for y, m, d in dates]
    return f"({' OR '.join(clauses)})"


def _lookback() -> str:
    return f"now() - interval '{settings.LOOKBACK_DAYS}' day"


def _get_base_ctes() -> str:
    p_filter = _partition_filter(settings.LOOKBACK_DAYS)
    return f"""
WITH orders_created AS (
    SELECT
        dados.id_order              AS id_order,
        from_iso8601_timestamp(event_timestamp) AS created_at,
        dados.id_restaurant         AS id_restaurant,
        dados.id_user               AS id_user,
        dados.id_courier            AS id_courier
    FROM events
    WHERE entidade = 'Order' AND acao = 'CREATE'
      AND dados.id_order IS NOT NULL
      AND {p_filter}
      AND from_iso8601_timestamp(event_timestamp) > {_lookback()}
),
transitions AS (
    SELECT dados.id_order AS id_order, 1 AS id_state,
           from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events
    WHERE entidade = 'Order' AND acao = 'CREATE' AND dados.id_order IS NOT NULL
      AND {p_filter}
      AND from_iso8601_timestamp(event_timestamp) > {_lookback()}
    UNION ALL
    SELECT dados.id_order AS id_order, dados.id_state AS id_state,
           from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events
    WHERE entidade = 'Order' AND acao = 'UPDATE' AND dados.id_order IS NOT NULL
      AND {p_filter}
      AND from_iso8601_timestamp(event_timestamp) > {_lookback()}
),
restaurants AS (
    SELECT dados.id_restaurant AS id_restaurant,
           max(dados.name)      AS name,
           max(dados.h3_index)  AS h3_index
    FROM events
    WHERE entidade = 'Restaurant' AND dados.id_restaurant IS NOT NULL
      AND {p_filter}
    GROUP BY dados.id_restaurant
)
"""


# ── 1. Volume de pedidos no tempo (por hora) ──────────────────────────────────
def volume_over_time() -> str:
    return _get_base_ctes() + """
    SELECT date_trunc('hour', created_at) AS bucket, count(*) AS orders
    FROM orders_created
    GROUP BY 1 ORDER BY 1
    """


# ── 2. Tempo médio em cada estado do ciclo de vida ────────────────────────────
def avg_time_per_state() -> str:
    return _get_base_ctes() + """
    , seq AS (
        SELECT id_order, id_state, changed_at,
               lead(changed_at) OVER (PARTITION BY id_order ORDER BY changed_at) AS next_at
        FROM transitions
    )
    SELECT id_state,
           avg(date_diff('second', changed_at, next_at)) AS avg_seconds,
           count(*) AS samples
    FROM seq
    WHERE next_at IS NOT NULL
    GROUP BY id_state ORDER BY id_state
    """


# ── 3. Distribuição de pedidos por região (célula H3 do restaurante) ──────────
def orders_by_region() -> str:
    return _get_base_ctes() + """
    SELECT CAST(r.h3_index AS varchar) AS region, count(*) AS orders
    FROM orders_created o
    JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    WHERE r.h3_index IS NOT NULL
    GROUP BY r.h3_index ORDER BY orders DESC
    LIMIT 25
    """


# ── 4. Heatmap de demanda por horário e dia da semana ─────────────────────────
def demand_heatmap() -> str:
    return _get_base_ctes() + """
    SELECT day_of_week(created_at) AS dow, hour(created_at) AS hr, count(*) AS orders
    FROM orders_created
    GROUP BY 1, 2
    """


# ── 5. Top 10 restaurantes por volume ─────────────────────────────────────────
def top_restaurants() -> str:
    return _get_base_ctes() + """
    SELECT o.id_restaurant AS id_restaurant,
           coalesce(max(r.name), concat('Restaurante #', CAST(o.id_restaurant AS varchar))) AS name,
           count(*) AS orders
    FROM orders_created o
    LEFT JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    GROUP BY o.id_restaurant ORDER BY orders DESC
    LIMIT 10
    """


# ── 6. Histograma do tempo total de entrega (bins de 5 min) ───────────────────
def delivery_time_histogram() -> str:
    return _get_base_ctes() + """
    , lifecycle AS (
        SELECT o.id_order, o.created_at,
               min(CASE WHEN t.id_state = 6 THEN t.changed_at END) AS delivered_at
        FROM orders_created o
        JOIN transitions t ON o.id_order = t.id_order
        GROUP BY o.id_order, o.created_at
    )
    SELECT CAST(floor(date_diff('second', created_at, delivered_at) / 300.0) * 5 AS integer) AS bin_min,
           count(*) AS orders
    FROM lifecycle
    WHERE delivered_at IS NOT NULL
      AND date_diff('second', created_at, delivered_at) BETWEEN 0 AND 21600
    GROUP BY 1 ORDER BY 1
    """


# ── Métricas instantâneas da operação (estado atual, via lake near-real-time) ──
def open_orders_by_state() -> str:
    """Pedidos ainda abertos (último estado < 6), por estado."""
    return _get_base_ctes() + """
    , ranked AS (
        SELECT id_order, id_state,
               row_number() OVER (PARTITION BY id_order ORDER BY changed_at DESC) AS rn
        FROM transitions
    )
    SELECT id_state, count(*) AS orders
    FROM ranked
    WHERE rn = 1 AND id_state < 6
    GROUP BY id_state ORDER BY id_state
    """


def active_couriers() -> str:
    """Entregadores que reportaram posição na última janela + quantos disponíveis."""
    p_filter = _partition_filter(1)
    return f"""
    WITH latest AS (
        SELECT dados.id_courier AS id_courier,
               dados.status     AS status,
               from_iso8601_timestamp(event_timestamp) AS ts,
               row_number() OVER (PARTITION BY dados.id_courier
                                  ORDER BY from_iso8601_timestamp(event_timestamp) DESC) AS rn
        FROM events
        WHERE entidade = 'Position' AND dados.id_courier IS NOT NULL
          AND {p_filter}
          AND from_iso8601_timestamp(event_timestamp) > now() - interval '30' minute
    )
    SELECT
        count(*)                                              AS active,
        count_if(status = 'AVAILABLE')                        AS available,
        count_if(status = 'BUSY')                             AS busy
    FROM latest WHERE rn = 1
    """


def kpis() -> str:
    """Cartões-resumo (KPIs) numa única query."""
    return _get_base_ctes() + """
    , lifecycle AS (
        SELECT o.id_order, o.created_at,
               min(CASE WHEN t.id_state = 6 THEN t.changed_at END) AS delivered_at
        FROM orders_created o
        JOIN transitions t ON o.id_order = t.id_order
        GROUP BY o.id_order, o.created_at
    )
    SELECT
        (SELECT count(*) FROM orders_created)                                   AS total_orders,
        (SELECT count(*) FROM orders_created
            WHERE created_at > now() - interval '1' hour)                       AS orders_last_hour,
        (SELECT count(*) FROM lifecycle WHERE delivered_at IS NOT NULL)         AS delivered_orders,
        (SELECT avg(date_diff('second', created_at, delivered_at)) / 60.0
            FROM lifecycle WHERE delivered_at IS NOT NULL)                      AS avg_delivery_min,
        (SELECT count(DISTINCT id_user) FROM orders_created)                    AS unique_users
    """

