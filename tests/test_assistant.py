"""Testes de lógica pura da camada conversacional (sem AWS)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "assistant-service"))

from src import sql_guard, fallback, engine, catalog  # noqa: E402


def test_sql_guard_accepts_select():
    out = sql_guard.sanitize("select count(*) from vw_orders")
    assert out.lower().startswith("select")
    # impõe LIMIT
    assert "limit" in sql_guard.sanitize("select * from vw_orders").lower()
    # remove cercas de código
    assert sql_guard.sanitize("```sql\nselect 1 from vw_orders\n```").lower().startswith("select")


def test_sql_guard_rejects_unsafe():
    bad = [
        "insert into vw_orders values (1)",
        "drop table vw_orders",
        "select 1 from vw_orders; drop table x",
        "update vw_orders set id_order=1",
        "select * from segredo_secreto",
    ]
    for b in bad:
        try:
            sql_guard.sanitize(b)
        except sql_guard.UnsafeSQL:
            continue
        raise AssertionError(f"deveria rejeitar: {b}")


def test_fallback_intents():
    sql, _ = fallback.to_sql("qual o tempo médio de entrega?")
    assert "vw_deliveries" in sql
    sql, _ = fallback.to_sql("quantos pedidos na última hora")
    assert "interval '1' hour" in sql
    sql, _ = fallback.to_sql("top restaurantes por volume")
    assert "order by pedidos desc" in sql.lower()


def test_chart_suggestion():
    ch = engine._suggest_chart([{"hora": "10h", "pedidos": 3}, {"hora": "11h", "pedidos": 5}])
    assert ch and ch["type"] == "line"
    assert engine._suggest_chart([{"total": 5}]) is None
    bar = engine._suggest_chart([{"regiao": "A", "pedidos": 9}, {"regiao": "B", "pedidos": 4}])
    assert bar and bar["type"] == "bar"


def test_catalog_prompt():
    p = catalog.catalog.schema_prompt()
    assert "vw_orders" in p and "vw_deliveries" in p


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  [ok] " + name)
    print("test_assistant OK")
