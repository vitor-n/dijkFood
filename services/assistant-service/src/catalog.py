"""
Catálogo semântico da camada conversacional.

Descreve o schema (views), um dicionário de negócio e exemplos few-shot usados
para guiar o text-to-SQL. Vem embutido por padrão e pode ser sobrescrito por
arquivos em s3://<datalake>/semantic/ (schema.json, dictionary.json, few_shots.json),
permitindo evoluir o "conhecimento" do assistente sem redeploy.
"""
from __future__ import annotations

import json
import logging

import boto3

from .config import settings

log = logging.getLogger("assistant.catalog")
_s3 = boto3.client("s3", region_name=settings.AWS_REGION)

DEFAULT_SCHEMA = {
    "dialect": "Trino/Athena (SQL ANSI)",
    "notes": [
        "Todos os timestamps estão em UTC.",
        "day_of_week(ts): 1=segunda ... 7=domingo. hour(ts): 0..23.",
        "região é a célula H3 do restaurante (coluna 'region').",
        "Estados do pedido: 1=Confirmado, 2=Preparando, 3=Pronto para retirada, 4=Retirado, 5=Em trânsito, 6=Entregue.",
        "Use date_diff('second', a, b) para diferenças de tempo. Sempre limite resultados grandes.",
    ],
    "tables": {
        "vw_orders": {
            "desc": "Um registro por pedido criado.",
            "columns": {
                "id_order": "id do pedido",
                "created_at": "timestamp de criação",
                "id_restaurant": "id do restaurante",
                "id_user": "id do cliente",
                "id_courier": "id do entregador atribuído",
            },
        },
        "vw_order_transitions": {
            "desc": "Uma linha por transição de estado do pedido (inclui a criação no estado 1).",
            "columns": {
                "id_order": "id do pedido",
                "id_state": "código do estado (1..6)",
                "state_name": "nome do estado",
                "changed_at": "quando a transição ocorreu",
            },
        },
        "vw_deliveries": {
            "desc": "Um registro por pedido ENTREGUE, com tempo total de entrega.",
            "columns": {
                "id_order": "id do pedido",
                "created_at": "criação",
                "delivered_at": "entrega",
                "delivery_minutes": "tempo total de entrega em minutos",
                "id_restaurant": "restaurante",
                "region": "célula H3 do restaurante",
            },
        },
        "vw_restaurants": {
            "desc": "Cadastro de restaurantes.",
            "columns": {
                "id_restaurant": "id", "name": "nome",
                "region": "célula H3", "lat": "latitude", "lon": "longitude",
            },
        },
        "vw_positions": {
            "desc": "Posições reportadas pelos entregadores (CDC do DynamoDB).",
            "columns": {
                "id_courier": "id do entregador", "lat": "latitude", "lon": "longitude",
                "status": "AVAILABLE | BUSY | OFFLINE", "reported_at": "quando foi reportada",
            },
        },
    },
}

DEFAULT_DICTIONARY = {
    "pedido": "linha em vw_orders",
    "entrega": "pedido que chegou ao estado 6 (vw_deliveries)",
    "tempo de entrega": "delivery_minutes em vw_deliveries",
    "região": "coluna region (célula H3 do restaurante)",
    "entregador disponível": "vw_positions.status = 'AVAILABLE'",
    "em andamento / aberto": "pedido cujo último estado é < 6",
    "hoje": "created_at >= date_trunc('day', now())",
    "última hora": "created_at > now() - interval '1' hour",
}

DEFAULT_FEW_SHOTS = [
    {
        "q": "Quantos pedidos foram criados na última hora?",
        "sql": "SELECT count(*) AS pedidos FROM vw_orders WHERE created_at > now() - interval '1' hour",
    },
    {
        "q": "Qual o tempo médio de entrega em minutos?",
        "sql": "SELECT round(avg(delivery_minutes), 1) AS tempo_medio_min FROM vw_deliveries",
    },
    {
        "q": "Top 5 restaurantes por volume de pedidos",
        "sql": (
            "SELECT r.name, count(*) AS pedidos FROM vw_orders o "
            "LEFT JOIN vw_restaurants r ON o.id_restaurant = r.id_restaurant "
            "GROUP BY r.name ORDER BY pedidos DESC LIMIT 5"
        ),
    },
    {
        "q": "Quantos pedidos estão em andamento em cada estado?",
        "sql": (
            "WITH last AS (SELECT id_order, id_state, "
            "row_number() OVER (PARTITION BY id_order ORDER BY changed_at DESC) rn "
            "FROM vw_order_transitions) "
            "SELECT id_state, count(*) AS pedidos FROM last WHERE rn=1 AND id_state<6 "
            "GROUP BY id_state ORDER BY id_state"
        ),
    },
    {
        "q": "Quantos entregadores estão disponíveis agora?",
        "sql": (
            "WITH latest AS (SELECT id_courier, status, "
            "row_number() OVER (PARTITION BY id_courier ORDER BY reported_at DESC) rn "
            "FROM vw_positions WHERE reported_at > now() - interval '30' minute) "
            "SELECT count(*) AS disponiveis FROM latest WHERE rn=1 AND status='AVAILABLE'"
        ),
    },
    {
        "q": "Distribuição de pedidos por região",
        "sql": (
            "SELECT r.region, count(*) AS pedidos FROM vw_orders o "
            "JOIN vw_restaurants r ON o.id_restaurant=r.id_restaurant "
            "GROUP BY r.region ORDER BY pedidos DESC LIMIT 20"
        ),
    },
]


class Catalog:
    def __init__(self) -> None:
        self.schema = DEFAULT_SCHEMA
        self.dictionary = DEFAULT_DICTIONARY
        self.few_shots = DEFAULT_FEW_SHOTS

    def load_overrides(self) -> None:
        if not settings.DATALAKE_BUCKET:
            return
        for attr, fname in (("schema", "schema.json"), ("dictionary", "dictionary.json"), ("few_shots", "few_shots.json")):
            key = f"{settings.SEMANTIC_PREFIX}/{fname}"
            try:
                obj = _s3.get_object(Bucket=settings.DATALAKE_BUCKET, Key=key)
                setattr(self, attr, json.loads(obj["Body"].read()))
                log.info("catálogo semântico sobrescrito por s3://%s/%s", settings.DATALAKE_BUCKET, key)
            except Exception:  # noqa: BLE001
                pass  # usa default

    def schema_prompt(self) -> str:
        lines = [f"Dialeto: {self.schema['dialect']}", "", "TABELAS/VIEWS DISPONÍVEIS:"]
        for tname, t in self.schema["tables"].items():
            lines.append(f"- {tname}: {t['desc']}")
            for col, desc in t["columns"].items():
                lines.append(f"    • {col} — {desc}")
        lines += ["", "REGRAS DE NEGÓCIO:"]
        lines += [f"- {n}" for n in self.schema["notes"]]
        lines += ["", "DICIONÁRIO:"]
        lines += [f"- {term}: {meaning}" for term, meaning in self.dictionary.items()]
        return "\n".join(lines)

    def few_shot_prompt(self) -> str:
        return "\n".join(f"Pergunta: {ex['q']}\nSQL: {ex['sql']}" for ex in self.few_shots)


catalog = Catalog()
