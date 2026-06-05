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

# Ordem importa: vw_deliveries depende das demais.
VIEW_DEFS: list[tuple[str, str]] = [
    ("vw_orders", """
        SELECT dados.id_order        AS id_order,
               from_iso8601_timestamp(event_timestamp) AS created_at,
               dados.id_restaurant   AS id_restaurant,
               dados.id_user         AS id_user,
               dados.id_courier      AS id_courier
        FROM events
        WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
    """),
    ("vw_order_transitions", """
        SELECT dados.id_order AS id_order, 1 AS id_state, 'Confirmado' AS state_name,
               from_iso8601_timestamp(event_timestamp) AS changed_at
        FROM events WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
        UNION ALL
        SELECT dados.id_order, dados.id_state,
               CASE dados.id_state
                    WHEN 2 THEN 'Preparando' WHEN 3 THEN 'Pronto para retirada'
                    WHEN 4 THEN 'Retirado'   WHEN 5 THEN 'Em transito'
                    WHEN 6 THEN 'Entregue'   ELSE 'Desconhecido' END,
               from_iso8601_timestamp(event_timestamp)
        FROM events WHERE entidade='Order' AND acao='UPDATE' AND dados.id_order IS NOT NULL
    """),
    ("vw_restaurants", """
        SELECT dados.id_restaurant AS id_restaurant,
               max(dados.name)     AS name,
               max(dados.h3_index) AS region,
               max(dados.lat)      AS lat,
               max(dados.lon)      AS lon
        FROM events WHERE entidade='Restaurant' AND dados.id_restaurant IS NOT NULL
        GROUP BY dados.id_restaurant
    """),
    ("vw_positions", """
        SELECT dados.id_courier AS id_courier, dados.lat AS lat, dados.lon AS lon,
               dados.status AS status,
               from_iso8601_timestamp(event_timestamp) AS reported_at
        FROM events WHERE entidade='Position' AND dados.id_courier IS NOT NULL
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
