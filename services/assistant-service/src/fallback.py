"""
Motor determinístico de fallback (sem LLM).

Casa a pergunta com intents conhecidas → SQL parametrizado sobre as views.
Garante que a camada conversacional funcione mesmo sem acesso ao Bedrock
(restrição do Learner Lab), de forma totalmente offline.
"""
from __future__ import annotations

import re

# (regex, sql, intent)
_INTENTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(quantos|n[uú]mero).*(pedido).*(hora|agora)", re.I),
     "SELECT count(*) AS pedidos_ultima_hora FROM vw_orders WHERE created_at > now() - interval '1' hour",
     "pedidos na última hora"),

    (re.compile(r"(quantos|total|n[uú]mero).*(pedido).*(hoje)", re.I),
     "SELECT count(*) AS pedidos_hoje FROM vw_orders WHERE created_at >= date_trunc('day', now())",
     "pedidos hoje"),

    (re.compile(r"(tempo|dura[cç][aã]o).*(m[eé]dio|medio|m[eé]dia).*(entrega)", re.I),
     "SELECT round(avg(delivery_minutes),1) AS tempo_medio_min, count(*) AS entregas FROM vw_deliveries",
     "tempo médio de entrega"),

    (re.compile(r"(top|melhores|maiores|mais).*(restaurante)", re.I),
     "SELECT r.name AS restaurante, count(*) AS pedidos FROM vw_orders o "
     "LEFT JOIN vw_restaurants r ON o.id_restaurant=r.id_restaurant "
     "GROUP BY r.name ORDER BY pedidos DESC LIMIT 10",
     "top restaurantes"),

    (re.compile(r"(regi[aã]o|regioes|regi[oõ]es|distribui)", re.I),
     "SELECT r.region AS regiao, count(*) AS pedidos FROM vw_orders o "
     "JOIN vw_restaurants r ON o.id_restaurant=r.id_restaurant "
     "GROUP BY r.region ORDER BY pedidos DESC LIMIT 20",
     "pedidos por região"),

    (re.compile(r"(entregador|courier).*(dispon[ií]vel|disponiveis|ativos|ativo)", re.I),
     "WITH latest AS (SELECT id_courier, status, "
     "row_number() OVER (PARTITION BY id_courier ORDER BY reported_at DESC) rn "
     "FROM vw_positions WHERE reported_at > now() - interval '30' minute) "
     "SELECT count_if(status='AVAILABLE') AS disponiveis, count(*) AS ativos "
     "FROM latest WHERE rn=1",
     "entregadores disponíveis"),

    (re.compile(r"(em andamento|aberto|abertos|pendente|cada estado|por estado)", re.I),
     "WITH last AS (SELECT id_order, id_state, state_name, "
     "row_number() OVER (PARTITION BY id_order ORDER BY changed_at DESC) rn "
     "FROM vw_order_transitions) "
     "SELECT id_state, max(state_name) AS estado, count(*) AS pedidos "
     "FROM last WHERE rn=1 AND id_state<6 GROUP BY id_state ORDER BY id_state",
     "pedidos abertos por estado"),

    (re.compile(r"(quantos|total|n[uú]mero).*(pedido)", re.I),
     "SELECT count(*) AS total_pedidos FROM vw_orders",
     "total de pedidos"),

    (re.compile(r"(quantas|quantos).*(entrega)", re.I),
     "SELECT count(*) AS total_entregas FROM vw_deliveries",
     "total de entregas"),
]

_DEFAULT_SQL = (
    "SELECT date_trunc('hour', created_at) AS hora, count(*) AS pedidos "
    "FROM vw_orders WHERE created_at > now() - interval '24' hour "
    "GROUP BY 1 ORDER BY 1"
)


def to_sql(question: str) -> tuple[str, str]:
    for pattern, sql, intent in _INTENTS:
        if pattern.search(question or ""):
            return sql, intent
    return _DEFAULT_SQL, "volume nas últimas 24h (resposta padrão)"
