"""Teste do envelope do outbox-publisher (driver pg8000 vendado + boto3)."""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("FIREHOSE_STREAM_NAME", "test-stream")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "dijkfood")
os.environ.setdefault("DB_USER", "u")
os.environ.setdefault("DB_PASSWORD", "p")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "infra", "lambda", "outbox_publisher"))

import index  # noqa: E402


def test_envelope_from_dict():
    ts = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    env = index._envelope("Order", "CREATE", {"id_order": 5}, ts)
    assert env["entidade"] == "Order" and env["acao"] == "CREATE"
    assert env["dados"]["id_order"] == 5
    assert env["timestamp"].startswith("2026-06-05T12:00")


def test_envelope_from_json_string():
    env = index._envelope("Order", "UPDATE", '{"id_order": 9, "id_state": 6}', "2026-06-05T10:00:00+00:00")
    assert env["dados"]["id_state"] == 6


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  [ok] " + name)
    print("test_outbox_lambda OK")
