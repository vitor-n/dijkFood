"""
Views curadas da camada conversacional.

Em vez de expor a tabela bruta `events` (struct aninhada) ao LLM, criamos views
limpas e nomeadas. Isso torna o text-to-SQL mais simples, seguro e auditável: o
modelo só "enxerga" estas views, e a validação restringe a execução a elas.
"""
from __future__ import annotations

import logging

from . import athena

log = logging.getLogger("assistant.views")

def _partition_filter(lookback_days: int) -> str:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    dates = []
    for i in range(-1, lookback_days + 2):
        d = now - timedelta(days=i)
        dates.append((d.strftime("%Y"), d.strftime("%m"), d.strftime("%d")))
    dates = sorted(list(set(dates)))
    clauses = [f"(year = '{y}' AND month = '{m}' AND day = '{d}')" for y, m, d in dates]
    return f"({' OR '.join(clauses)})"

p_filter = _partition_filter(60)

# Ordem importa: vw_deliveries depende das demais.
VIEW_DEFS: list[tuple[str, str]] = [
    ("vw_orders", f"""
        SELECT dados.id_order        AS id_order,
               cast(from_iso8601_timestamp(event_timestamp) as timestamp) AS created_at,
               dados.id_restaurant   AS id_restaurant,
               dados.id_user         AS id_user,
               dados.id_courier      AS id_courier
        FROM events
        WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
          AND {p_filter}
    """),
    ("vw_order_transitions", f"""
        SELECT dados.id_order AS id_order, 1 AS id_state, 'Confirmado' AS state_name,
               cast(from_iso8601_timestamp(event_timestamp) as timestamp) AS changed_at
        FROM events WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
          AND {p_filter}
        UNION ALL
        SELECT dados.id_order, dados.id_state,
               CASE dados.id_state
                    WHEN 2 THEN 'Preparando' WHEN 3 THEN 'Pronto para retirada'
                    WHEN 4 THEN 'Retirado'   WHEN 5 THEN 'Em transito'
                    WHEN 6 THEN 'Entregue'   ELSE 'Desconhecido' END,
               cast(from_iso8601_timestamp(event_timestamp) as timestamp)
        FROM events WHERE entidade='Order' AND acao='UPDATE' AND dados.id_order IS NOT NULL
          AND {p_filter}
    """),
    ("vw_restaurants", f"""
        SELECT dados.id_restaurant AS id_restaurant,
               max(dados.name)     AS name,
               max(dados.h3_index) AS region,
               max(dados.lat)      AS lat,
               max(dados.lon)      AS lon
        FROM events WHERE entidade='Restaurant' AND dados.id_restaurant IS NOT NULL
          AND {p_filter}
        GROUP BY dados.id_restaurant
    """),
    ("vw_positions", f"""
        SELECT dados.id_courier AS id_courier, dados.lat AS lat, dados.lon AS lon,
               dados.status AS status,
               cast(from_iso8601_timestamp(event_timestamp) as timestamp) AS reported_at
        FROM events WHERE entidade='Position' AND dados.id_courier IS NOT NULL
          AND {p_filter}
    """),
    ("vw_deliveries", """
        SELECT o.id_order, o.created_at, o.id_restaurant, r.region,
               d.delivered_at,
               date_diff('second', o.created_at, d.delivered_at) / 60.0 AS delivery_minutes
        FROM vw_orders o
        JOIN (
            SELECT id_order, min(changed_at) AS delivered_at
            FROM vw_order_transitions WHERE id_state = 6 GROUP BY id_order
        ) d ON o.id_order = d.id_order
        LEFT JOIN vw_restaurants r ON o.id_restaurant = r.id_restaurant
    """),
    ("vw_items", f"""
        SELECT dados.id_item        AS id_item,
               dados.name           AS name,
               dados.id_restaurant  AS id_restaurant
        FROM events
        WHERE entidade='MenuItem' AND acao='CREATE' AND dados.id_item IS NOT NULL
          AND {{p_filter}}
    """),
    ("vw_order_items", f"""
        SELECT dados.id_order               AS id_order,
               CAST(item.id_item AS INTEGER) AS id_item,
               CAST(item.price AS DOUBLE)    AS price
        FROM events
        CROSS JOIN UNNEST(dados.items) AS t(item)
        WHERE entidade='Order' AND acao='CREATE' AND dados.items IS NOT NULL
          AND {{p_filter}}
    """),
]

ALLOWED_TABLES = {"events"} | {name for name, _ in VIEW_DEFS}


def bootstrap_views() -> None:
    """Cria/atualiza as views no Glue via Athena (idempotente)."""
    for name, body in VIEW_DEFS:
        ddl = f"CREATE OR REPLACE VIEW {name} AS {body.strip()}"
        try:
            athena.execute(ddl, ddl=True, timeout=60)
            log.info("view %s pronta", name)
        except Exception as exc:  # noqa: BLE001
            log.warning("falha ao criar view %s: %s", name, exc)
