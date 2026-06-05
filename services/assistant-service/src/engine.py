"""
Orquestração da pergunta conversacional:

  pergunta (NL)
    → Bedrock text-to-SQL  (ou motor determinístico se indisponível)
    → guard de segurança (SELECT-only, allowlist, LIMIT)
    → Athena
    → resposta em linguagem natural + dados + sugestão de gráfico

Nunca lança para o usuário: degrada graciosamente para o fallback.
"""
from __future__ import annotations

import logging
from typing import Any

from . import athena, fallback, nl2sql, sql_guard
from .config import settings

log = logging.getLogger("assistant.engine")


def _suggest_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    cols = list(rows[0].keys())
    if len(rows) == 1 and len(cols) <= 2:
        return None  # escalar — sem gráfico
    if len(cols) < 2:
        return None
    label_col = cols[0]
    num_col = next((c for c in cols[1:] if isinstance(rows[0].get(c), (int, float))), None)
    if num_col is None:
        return None
    is_time = any(k in label_col.lower() for k in ("hora", "data", "bucket", "created", "ts", "time"))
    return {
        "type": "line" if is_time else "bar",
        "x": [r.get(label_col) for r in rows],
        "y": [r.get(num_col) for r in rows],
        "x_label": label_col,
        "y_label": num_col,
    }


def _template_answer(rows: list[dict[str, Any]], intent: str | None) -> str:
    if not rows:
        return "Não encontrei dados para essa pergunta na janela disponível."
    if len(rows) == 1 and len(rows[0]) == 1:
        (k, v), = rows[0].items()
        return f"{k.replace('_', ' ').capitalize()}: **{v}**."
    if len(rows) == 1:
        parts = ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in rows[0].items())
        return f"Resultado: {parts}."
    head = rows[0]
    label = list(head.keys())[0]
    metric = list(head.keys())[-1]
    top = ", ".join(f"{r.get(label)} ({r.get(metric)})" for r in rows[:3])
    prefix = f"({intent}) " if intent else ""
    return f"{prefix}Retornei {len(rows)} linhas. Destaques por {metric}: {top}."


def answer(question: str) -> dict[str, Any]:
    source = "fallback"
    intent: str | None = None
    sql: str | None = None
    error: str | None = None

    # 1) Tenta Bedrock
    if settings.USE_BEDROCK:
        try:
            raw = nl2sql.generate_sql(question)
            sql = sql_guard.sanitize(raw)
            rows = athena.execute(sql)
            source = "bedrock"
            nl = nl2sql.summarize(question, sql, rows) or _template_answer(rows, None)
            return _result(nl, sql, source, rows, intent, None)
        except Exception as exc:  # noqa: BLE001
            log.info("caminho Bedrock falhou (%s) — usando fallback", exc)
            error = str(exc)

    # 2) Fallback determinístico
    try:
        fb_sql, intent = fallback.to_sql(question)
        sql = sql_guard.sanitize(fb_sql)
        rows = athena.execute(sql)
        nl = _template_answer(rows, intent)
        return _result(nl, sql, source, rows, intent, error)
    except Exception as exc:  # noqa: BLE001
        log.warning("fallback também falhou: %s", exc)
        return _result(
            "Não consegui consultar a camada analítica agora. "
            "Verifique se há eventos no lake e se o Athena/Glue está provisionado.",
            sql, source, [], intent, str(exc),
        )


def _result(nl, sql, source, rows, intent, error):
    return {
        "answer": nl,
        "sql": sql,
        "source": source,
        "intent": intent,
        "rows": rows[: settings.MAX_ROWS],
        "row_count": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "chart": _suggest_chart(rows),
        "error": error,
    }
