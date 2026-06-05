"""
Text-to-SQL via Amazon Bedrock

Monta o prompt com o schema das views, o dicionário de negócio e exemplos
few-shot, e pede ao modelo APENAS o SQL. Se o Bedrock não estiver disponível
(ex.: conta sem acesso), o engine cai no motor determinístico (fallback.py).
"""
from __future__ import annotations

import logging

import boto3
from botocore.config import Config as BotoConfig

from .catalog import catalog
from .config import settings

log = logging.getLogger("assistant.nl2sql")

_bedrock = None


def _client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=settings.BEDROCK_REGION,
            config=BotoConfig(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=25),
        )
    return _bedrock


_SYSTEM = (
    "Você é um tradutor de linguagem natural para SQL (Trino/Athena) sobre a "
    "operação de delivery DijkFood. Responda SEMPRE com um único SELECT válido, "
    "sem comentários, sem explicações e sem cercas de código. Use apenas as "
    "views fornecidas. Sempre inclua LIMIT quando o resultado puder ser grande."
)


def generate_sql(question: str) -> str:
    prompt = (
        f"{catalog.schema_prompt()}\n\n"
        f"EXEMPLOS:\n{catalog.few_shot_prompt()}\n\n"
        f"Pergunta: {question}\nSQL:"
    )
    resp = _client().converse(
        modelId=settings.BEDROCK_MODEL_ID,
        system=[{"text": _SYSTEM}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 600, "temperature": 0.0, "topP": 0.9},
    )
    parts = resp["output"]["message"]["content"]
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Bedrock retornou resposta vazia")
    return text


def summarize(question: str, sql: str, rows: list[dict]) -> str | None:
    """Resumo em linguagem natural das linhas (best-effort; None se falhar)."""
    try:
        sample = rows[:30]
        prompt = (
            f"Pergunta do usuário: {question}\n"
            f"SQL executado: {sql}\n"
            f"Resultado (até 30 linhas, JSON): {sample}\n\n"
            "Responda em português, de forma direta e objetiva (1-3 frases), "
            "interpretando o resultado para um operador de delivery. "
            "Não invente números que não estejam no resultado."
        )
        resp = _client().converse(
            modelId=settings.BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.2},
        )
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception as exc:  # noqa: BLE001
        log.info("summarize via Bedrock falhou: %s", exc)
        return None
