"""
Guard de segurança do SQL gerado.

Garante que apenas SELECTs de leitura, sobre as views permitidas, cheguem ao
Athena: statement único, sem DDL/DML, tabelas ⊆ allowlist, com LIMIT imposto.
"""
from __future__ import annotations

import re

from .config import settings
from .views import ALLOWED_TABLES

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|merge|"
    r"call|msck|unload|replace|attach|set|reset)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", re.IGNORECASE)
_CTE_NAME = re.compile(r"(?:with|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", re.IGNORECASE)
_LIMIT = re.compile(r"\blimit\s+\d+\s*$", re.IGNORECASE)


class UnsafeSQL(ValueError):
    pass


def sanitize(sql: str) -> str:
    sql = (sql or "").strip()
    # Remove cercas de código que o LLM eventualmente devolve.
    sql = re.sub(r"^```(?:sql)?|```$", "", sql, flags=re.IGNORECASE | re.MULTILINE).strip()
    sql = sql.rstrip(";").strip()
    if not sql:
        raise UnsafeSQL("SQL vazio")

    if ";" in sql:
        raise UnsafeSQL("Apenas um único statement é permitido")

    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise UnsafeSQL("Apenas consultas SELECT são permitidas")

    if _FORBIDDEN.search(sql):
        raise UnsafeSQL("Comando não permitido (somente leitura)")

    cte_names = {m.lower() for m in _CTE_NAME.findall(sql)}
    for ref in _TABLE_REF.findall(sql):
        base = ref.split(".")[-1].lower()
        if base in cte_names or base in {t.lower() for t in ALLOWED_TABLES}:
            continue
        raise UnsafeSQL(f"Tabela não permitida: {ref}")

    if not _LIMIT.search(sql):
        sql = f"{sql}\nLIMIT {settings.MAX_ROWS}"
    return sql
