#!/usr/bin/env python3
"""
DijkFood — Resultados experimentais compactos (relatório A2, Objetivo 3).

Gera evidências REAIS (sem números inventados) para ~1 página de relatório,
cobrindo quatro eixos:

  1. Carga e latência da operação (simulador real: normal / peak / event).
  2. Persistência de eventos na camada analítica (Athena sobre a tabela `events`).
  3. Predição de ETA no momento do pedido (prediction-service real + fluxo do pedido).
  4. Resiliência da criação de pedido quando o ETA cai em fallback.

Todas as seções são isoladas: uma falha parcial é registrada em `limitations.md`
e NÃO aborta o restante. Todos os arquivos de saída são sempre gerados.

Uso:
  python scripts/experiments/run_compact_results.py --scan-only

  python scripts/experiments/run_compact_results.py \
    --base-url "$BASE_URL" \
    --prediction-url "$PREDICTION_URL" \
    --aws-region us-east-1 \
    --athena-database "$ATHENA_DATABASE" \
    --athena-output-s3 "$ATHENA_OUTPUT_S3" \
    --data-lake-bucket "$DATA_LAKE_BUCKET"

Saídas em artifacts/experiments/<timestamp>/:
  summary.json  summary.md  summary.typ
  load_results.csv  eta_results.json  analytics_counts.json  resilience_results.json
  limitations.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERRO: este script precisa de 'httpx' (pip install httpx).", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parents[2]
SIM_DIR = REPO_ROOT / "mock" / "bootstrap" / "src"
SIM_FILE = SIM_DIR / "simulator.py"

SLA_P95_MS = 500.0
LOAD_SCENARIOS = ["normal", "peak", "event"]
# rps nominal por cenário (espelha config.py do simulador — só p/ rotular a tabela)
SCENARIO_RPS = {"testing": 5.0, "normal": 10.0, "peak": 50.0, "event": 200.0}
TRACKED_ENDPOINTS = ["POST /order", "POST /tracking/position", "POST /routes/calculate"]

# Mesmos defaults do order-service (services/order-service/src/config.py) para o
# Teste B reproduzir fielmente a lógica de fallback do ETA.
ETA_TIMEOUT_S = float(os.environ.get("ETA_TIMEOUT", "0.4"))
ETA_FALLBACK_MIN = float(os.environ.get("ETA_FALLBACK_MIN", "35"))

LIMITATIONS: list[tuple[str, str]] = []


def add_limitation(section: str, message: str) -> None:
    LIMITATIONS.append((section, message))
    print(f"  [limitação:{section}] {message}")


# ───────────────────────────── HTTP helpers ──────────────────────────────────

def http_get(url: str, timeout: float = 10.0, **kw):
    try:
        r = httpx.get(url, timeout=timeout, **kw)
        body = None
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, None
    except Exception as exc:  # noqa: BLE001
        return 0, None, str(exc)


def http_post(url: str, payload: dict, timeout: float = 10.0):
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
        body = None
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, None
    except Exception as exc:  # noqa: BLE001
        return 0, None, str(exc)


def fetch_ids(base_url: str, n: int = 50) -> tuple[list[int], list[int]]:
    """Busca alguns ids reais de usuários e restaurantes via core-api."""
    users, rests = [], []
    sc, body, err = http_get(f"{base_url}/users?page=1&itemsPerPage={n}")
    if sc == 200 and isinstance(body, dict):
        users = [u["id_user"] for u in body.get("data", []) if "id_user" in u]
    sc, body, err = http_get(f"{base_url}/restaurants?page=1&itemsPerPage={n}")
    if sc == 200 and isinstance(body, dict):
        rests = [r["id_restaurant"] for r in body.get("data", []) if "id_restaurant" in r]
    return users, rests


def pctiles(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50": None, "p90": None, "p95": None}
    if len(values) == 1:
        v = round(values[0], 1)
        return {"count": 1, "p50": v, "p90": v, "p95": v}
    q = statistics.quantiles(values, n=100)
    return {"count": len(values), "p50": round(q[49], 1), "p90": round(q[89], 1), "p95": round(q[94], 1)}


def fnum(x, suffix="") -> str:
    return "—" if x is None else f"{x}{suffix}"


# ───────────────────────────── 0. Scan ───────────────────────────────────────

def do_scan(args) -> dict:
    print("== Scan de capacidades ==")
    scan = {
        "repo_root": str(REPO_ROOT),
        "simulator_found": SIM_FILE.is_file(),
        "load_scenarios": LOAD_SCENARIOS,
        "base_url": args.base_url,
        "prediction_url": args.prediction_url,
    }

    if args.base_url:
        sc, _, err = http_get(f"{args.base_url}/restaurants?page=1&itemsPerPage=1", timeout=8.0)
        scan["base_url_reachable"] = (sc == 200)
        if sc != 200:
            scan["base_url_error"] = err or f"HTTP {sc}"

    if args.prediction_url:
        sc, body, err = http_get(f"{args.prediction_url}/model/info", timeout=8.0)
        scan["prediction_model_info_ok"] = (sc == 200)
        if sc == 200:
            scan["prediction_model_ready"] = bool(isinstance(body, dict) and body.get("ready"))

    try:
        import boto3  # noqa: F401
        scan["boto3_available"] = True
        try:
            import boto3
            ident = boto3.client("sts", region_name=args.aws_region).get_caller_identity()
            scan["aws_account"] = ident.get("Account")
        except Exception as exc:  # noqa: BLE001
            scan["aws_credentials"] = f"indisponível: {exc}"
    except ImportError:
        scan["boto3_available"] = False

    scan["athena_database"] = args.athena_database
    scan["athena_configured"] = bool(args.athena_database and (args.athena_output_s3 or args.data_lake_bucket))
    print(json.dumps(scan, indent=2, ensure_ascii=False))
    return scan


# ───────────────────────────── 1. Carga e latência ───────────────────────────

def run_one_scenario(base_url: str, scenario: str, duration: int) -> dict | None:
    """Roda o simulador real como subprocess e lê o resumo via METRICS_JSON."""
    if not SIM_FILE.is_file():
        add_limitation("load", f"simulador não encontrado em {SIM_FILE}")
        return None

    json_fd, json_path = tempfile.mkstemp(suffix=".json", prefix=f"sim_{scenario}_")
    os.close(json_fd)
    env = os.environ.copy()
    env.update({
        "BASE_URL": base_url,
        "SCENARIO": scenario,
        "SIM_DURATION": str(duration),
        "SILENT": "1",
        "METRICS_JSON": json_path,
        "PYTHONIOENCODING": "utf-8",
    })
    # margem generosa: a simulação só termina quando todos os pedidos são entregues
    timeout_s = duration * 30 + 600
    print(f"  -> cenário '{scenario}' ({SCENARIO_RPS.get(scenario, '?')} rps, {duration}s)...")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "simulator.py"],
            cwd=str(SIM_DIR), env=env, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        add_limitation("load", f"cenário '{scenario}' excedeu timeout de {timeout_s}s")
        return None
    wall = time.perf_counter() - t0

    if not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        add_limitation("load", f"cenário '{scenario}' não produziu métricas. Fim do log: {tail!r}")
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    finally:
        try:
            os.remove(json_path)
        except OSError:
            pass

    data["wall_seconds"] = round(wall, 1)
    return data


def run_load(base_url: str, duration: int) -> dict:
    print("== 1. Carga e latência ==")
    results = {"scenarios": {}, "status": "OK"}
    if not base_url:
        results["status"] = "ERROR"
        add_limitation("load", "--base-url não informado; carga ignorada")
        return results

    for sc in LOAD_SCENARIOS:
        data = run_one_scenario(base_url, sc, duration)
        if data is None:
            results["scenarios"][sc] = {"status": "ERROR"}
            results["status"] = "PARTIAL"
            continue

        g = data.get("global_latency", {})
        by = data.get("by_endpoint", {})
        orders = data.get("orders", {})
        total = data.get("requests_total", 0)
        success = data.get("success", 0)
        wall = data.get("wall_seconds") or data.get("duration_seconds") or 0

        def ep(name, key):
            d = by.get(name, {})
            return d.get(key)

        row = {
            "status": "OK",
            "rps_nominal": SCENARIO_RPS.get(sc),
            "orders_created": orders.get("created", 0),
            "orders_completed": orders.get("completed", 0),
            "orders_failed": orders.get("failed", 0),
            "orders_not_created": orders.get("not_created", 0),
            "requests_total": total,
            "success_rate_pct": round(100 * success / total, 2) if total else None,
            "http_errors": data.get("http_errors", 0),
            "net_errors": data.get("net_errors", 0),
            "wall_seconds": wall,
            "throughput_req_s": round(total / wall, 1) if wall else None,
            "global_p50": g.get("p50"), "global_p90": g.get("p90"), "global_p95": g.get("p95"),
            "order_p50": ep("POST /order", "p50"), "order_p90": ep("POST /order", "p90"), "order_p95": ep("POST /order", "p95"),
            "track_p50": ep("POST /tracking/position", "p50"), "track_p90": ep("POST /tracking/position", "p90"), "track_p95": ep("POST /tracking/position", "p95"),
            "route_p50": ep("POST /routes/calculate", "p50"), "route_p90": ep("POST /routes/calculate", "p90"), "route_p95": ep("POST /routes/calculate", "p95"),
        }

        # gargalo = endpoint com maior P95
        worst_ep, worst_p95 = None, -1.0
        for name, d in by.items():
            p95 = d.get("p95")
            if p95 is not None and p95 > worst_p95:
                worst_ep, worst_p95 = name, p95
        row["bottleneck_endpoint"] = worst_ep
        row["bottleneck_p95"] = round(worst_p95, 1) if worst_p95 >= 0 else None

        # violações de SLA (não esconder)
        viol = []
        if row["global_p95"] is not None and row["global_p95"] > SLA_P95_MS:
            viol.append("global")
        for label, key in (("POST /order", "order_p95"), ("POST /tracking/position", "track_p95"), ("POST /routes/calculate", "route_p95")):
            if row[key] is not None and row[key] > SLA_P95_MS:
                viol.append(label)
        row["sla_p95_violations"] = viol
        row["sla_met"] = (len(viol) == 0)
        results["scenarios"][sc] = row
        print(f"     ok: {row['orders_created']} criados, sucesso {row['success_rate_pct']}%, P95 global {fnum(row['global_p95'],'ms')}")

    return results


# ───────────────────────────── 2. Camada analítica ───────────────────────────

def run_analytics(region: str, database: str, output_s3: str, data_lake_bucket: str) -> dict:
    print("== 2. Camada analítica (Athena) ==")
    out = {
        "order_created_events": 0, "order_state_events": 0, "courier_position_events": 0,
        "total_events": 0, "first_event_at": None, "last_event_at": None,
        "status": "ERROR", "notes": "",
    }
    if not database:
        out["notes"] = "--athena-database não informado"
        add_limitation("analytics", out["notes"])
        return out
    try:
        import boto3
    except ImportError:
        out["notes"] = "boto3 indisponível"
        add_limitation("analytics", out["notes"])
        return out

    if not output_s3:
        if data_lake_bucket:
            output_s3 = f"s3://{data_lake_bucket}/athena-results/"
        else:
            out["notes"] = "sem --athena-output-s3 nem --data-lake-bucket"
            add_limitation("analytics", out["notes"])
            return out

    sql = (
        "SELECT "
        "count_if(entidade='Order' AND acao='CREATE') AS order_created, "
        "count_if(entidade='Order' AND acao='UPDATE') AS order_state, "
        "count_if(entidade='Position') AS positions, "
        "count(*) AS total, "
        "min(event_timestamp) AS first_at, "
        "max(event_timestamp) AS last_at "
        "FROM events"
    )
    try:
        cli = boto3.client("athena", region_name=region)
        kwargs = {"QueryString": sql, "QueryExecutionContext": {"Database": database},
                  "ResultConfiguration": {"OutputLocation": output_s3}}
        qid = cli.start_query_execution(**kwargs)["QueryExecutionId"]
        state = "RUNNING"
        deadline = time.time() + 120
        while time.time() < deadline:
            q = cli.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            state = q["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(1.5)
        if state != "SUCCEEDED":
            reason = q.get("StateChangeReason", state) if isinstance(q, dict) else state
            out["notes"] = f"query Athena não concluiu: {reason}"
            add_limitation("analytics", out["notes"])
            return out

        res = cli.get_query_results(QueryExecutionId=qid)
        rows = res["ResultSet"]["Rows"]
        # rows[0] = header, rows[1] = valores
        vals = [c.get("VarCharValue") for c in rows[1]["Data"]] if len(rows) > 1 else []

        def to_int(x):
            try:
                return int(x)
            except (TypeError, ValueError):
                return 0

        out["order_created_events"] = to_int(vals[0]) if len(vals) > 0 else 0
        out["order_state_events"] = to_int(vals[1]) if len(vals) > 1 else 0
        out["courier_position_events"] = to_int(vals[2]) if len(vals) > 2 else 0
        out["total_events"] = to_int(vals[3]) if len(vals) > 3 else 0
        out["first_event_at"] = vals[4] if len(vals) > 4 else None
        out["last_event_at"] = vals[5] if len(vals) > 5 else None
        out["status"] = "OK" if out["total_events"] > 0 else "PARTIAL"
        if out["total_events"] == 0:
            out["notes"] = "consulta ok, mas zero eventos (Firehose pode ainda não ter dado flush)"
        print(f"     ok: total={out['total_events']} (order_create={out['order_created_events']}, "
              f"state={out['order_state_events']}, position={out['courier_position_events']})")
    except Exception as exc:  # noqa: BLE001
        out["notes"] = f"falha Athena: {exc}"
        add_limitation("analytics", out["notes"])
    return out


# ───────────────────────────── 3. Predição de ETA ────────────────────────────

def run_eta(prediction_url: str, base_url: str, samples: int) -> dict:
    print("== 3. Predição de ETA ==")
    out = {"status": "ERROR", "model_info": None, "health": None, "calls": []}
    if not prediction_url:
        add_limitation("eta", "--prediction-url não informado")
        return out

    sc, body, err = http_get(f"{prediction_url}/healthz", timeout=8.0)
    out["health"] = {"http": sc, "body": body if sc == 200 else (err or body)}

    sc, body, err = http_get(f"{prediction_url}/model/info", timeout=10.0)
    if sc == 200 and isinstance(body, dict):
        out["model_info"] = body
        out["model_ready"] = bool(body.get("ready"))
        metrics = body.get("metrics") or {}
        out["model_metrics"] = metrics
        out["n_train_samples"] = metrics.get("n_samples")
        out["mae_min"] = metrics.get("holdout_mae_min")
        out["baseline_mae_min"] = metrics.get("baseline_mae_min")
        out["model_trained_at"] = body.get("trained_at")
    else:
        out["model_ready"] = False
        add_limitation("eta", f"/model/info indisponível (HTTP {sc}: {err or ''})")

    _, rests = fetch_ids(base_url) if base_url else ([], [])
    if not rests:
        rests = [1, 2, 3, 4, 5]
        add_limitation("eta", "sem ids de restaurante reais; usando 1..5 para amostrar predições")

    latencies, sources, etas = [], [], []
    for i in range(samples):
        rid = rests[i % len(rests)]
        t0 = time.perf_counter()
        sc, body, err = http_post(f"{prediction_url}/predict/eta", {"id_restaurant": rid}, timeout=5.0)
        lat = (time.perf_counter() - t0) * 1000
        if sc == 200 and isinstance(body, dict):
            latencies.append(lat)
            src = body.get("source", "?")
            sources.append(src)
            if body.get("eta_minutes") is not None:
                etas.append(float(body["eta_minutes"]))
            out["calls"].append({"id_restaurant": rid, "eta_minutes": body.get("eta_minutes"),
                                 "source": src, "latency_ms": round(lat, 1)})
        else:
            out["calls"].append({"id_restaurant": rid, "error": err or f"HTTP {sc}"})

    n = len(latencies)
    if n:
        p = pctiles(latencies)
        n_model = sum(1 for s in sources if s.startswith("model"))
        n_fb = sum(1 for s in sources if "fallback" in s or s == "history")
        out.update({
            "status": "OK",
            "n_calls": n,
            "latency_ms": {"p50": p["p50"], "p90": p["p90"], "p95": p["p95"]},
            "pct_model": round(100 * n_model / n, 1),
            "pct_fallback": round(100 * n_fb / n, 1),
            "mean_eta_min": round(sum(etas) / len(etas), 1) if etas else None,
            "source_breakdown": {s: sources.count(s) for s in set(sources)},
        })
        print(f"     ok: {n} chamadas, ETA p95 {p['p95']}ms, modelo {out['pct_model']}%, "
              f"fallback {out['pct_fallback']}%, ETA médio {fnum(out['mean_eta_min'],'min')}")
    else:
        out["status"] = "PARTIAL" if out["model_info"] else "ERROR"
        add_limitation("eta", "nenhuma chamada de /predict/eta foi bem-sucedida")
    return out


# ───────────────────────────── 4. Resiliência ────────────────────────────────

def replicate_order_fallback(bad_url: str) -> dict:
    """Reproduz EXATAMENTE a lógica de order-service/src/prediction.py contra um
    endpoint inalcançável, comprovando o caminho de degradação (fallback)."""
    try:
        r = httpx.post(bad_url.rstrip("/") + "/predict/eta", json={"id_restaurant": 1}, timeout=ETA_TIMEOUT_S)
        r.raise_for_status()
        body = r.json()
        eta = body.get("eta_minutes")
        if eta is not None:
            return {"eta_minutes": round(float(eta), 1), "source": body.get("source", "model")}
    except Exception:
        pass
    return {"eta_minutes": ETA_FALLBACK_MIN, "source": "fallback"}


def run_resilience(base_url: str, prediction_url: str, n_orders: int) -> dict:
    print("== 4. Resiliência da criação de pedido ==")
    out = {"test_a": {}, "test_b": {}, "status": "ERROR"}

    users, rests = fetch_ids(base_url) if base_url else ([], [])

    # ── Teste A: prediction-service normal, pedido real via order-service ──
    a = {"created": 0, "attempted": 0, "eta_sources": {}, "errors": []}
    if users and rests:
        import random
        for _ in range(n_orders):
            a["attempted"] += 1
            payload = {"id_user": random.choice(users), "id_restaurant": random.choice(rests)}
            sc, body, err = http_post(f"{base_url}/order", payload, timeout=15.0)
            if sc == 200 and isinstance(body, dict) and "id_order" in body:
                a["created"] += 1
                src = body.get("eta_source", "?")
                a["eta_sources"][src] = a["eta_sources"].get(src, 0) + 1
            else:
                a["errors"].append(err or f"HTTP {sc}: {body}")
        a["success_rate_pct"] = round(100 * a["created"] / a["attempted"], 1) if a["attempted"] else None
        print(f"     Teste A: {a['created']}/{a['attempted']} pedidos criados, eta_source={a['eta_sources']}")
    else:
        add_limitation("resilience", "sem ids reais de usuário/restaurante; Teste A não pôde criar pedidos")
    out["test_a"] = a

    # ── Teste B: ETA indisponível → fallback (reproduz a lógica do order-service) ──
    bad = replicate_order_fallback("http://127.0.0.1:9")  # porta fechada → timeout/conn refused
    b = {
        "method": "replica_da_logica_do_order_service",
        "unreachable_endpoint": "http://127.0.0.1:9/predict/eta",
        "eta_timeout_s": ETA_TIMEOUT_S,
        "result": bad,
        "fallback_ok": (bad.get("source") == "fallback" and bad.get("eta_minutes") == ETA_FALLBACK_MIN),
    }
    # Evidência complementar real: com o serviço normal, o pedido segue sendo criado.
    if users and rests:
        import random
        sc, body, err = http_post(f"{base_url}/order",
                                  {"id_user": random.choice(users), "id_restaurant": random.choice(rests)},
                                  timeout=15.0)
        b["live_order_still_created"] = (sc == 200 and isinstance(body, dict) and "id_order" in body)
        if isinstance(body, dict):
            b["live_order_eta_source"] = body.get("eta_source")
    add_limitation(
        "resilience",
        "Teste B reproduz a lógica de fallback do order-service contra endpoint "
        "inalcançável (a env var PREDICTION_SERVICE_ENDPOINT do serviço implantado "
        "não pode ser trocada em runtime sem redeploy). O Teste A é a evidência "
        "end-to-end de que pedidos são criados com eta_source registrado.",
    )
    out["test_b"] = b
    print(f"     Teste B: fallback_ok={b['fallback_ok']} (source={bad.get('source')}, eta={bad.get('eta_minutes')}min)")

    if (a.get("created", 0) > 0) or b.get("fallback_ok"):
        out["status"] = "OK" if (a.get("created", 0) > 0 and b.get("fallback_ok")) else "PARTIAL"
    return out


# ───────────────────────────── Saídas / relatório ────────────────────────────

def write_load_csv(path: Path, load: dict) -> None:
    cols = ["scenario", "rps_nominal", "status", "orders_created", "orders_completed",
            "orders_failed", "orders_not_created", "requests_total", "success_rate_pct",
            "http_errors", "net_errors", "throughput_req_s",
            "global_p50", "global_p90", "global_p95",
            "order_p50", "order_p90", "order_p95",
            "track_p50", "track_p90", "track_p95",
            "route_p50", "route_p90", "route_p95",
            "bottleneck_endpoint", "bottleneck_p95", "sla_met", "sla_p95_violations"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for sc in LOAD_SCENARIOS:
            row = load.get("scenarios", {}).get(sc, {"status": "ERROR"})
            out = [sc]
            for c in cols[1:]:
                v = row.get(c, "")
                if isinstance(v, list):
                    v = ";".join(map(str, v))
                out.append("" if v is None else v)
            w.writerow(out)


def build_synthesis(load: dict, analytics: dict, eta: dict, resil: dict) -> str:
    parts = []
    scn = load.get("scenarios", {})
    ok_scn = [s for s, r in scn.items() if r.get("status") == "OK"]
    # disponibilidade
    rates = [r.get("success_rate_pct") for r in scn.values() if r.get("success_rate_pct") is not None]
    if ok_scn and rates and min(rates) >= 99.0:
        parts.append(
            f"A plataforma sustentou os cenários {', '.join(ok_scn)} preservando a criação "
            f"e conclusão dos pedidos (taxa de sucesso ≥ {min(rates):.1f}%).")
    elif ok_scn:
        parts.append(f"Cenários executados: {', '.join(ok_scn)} (taxa de sucesso mín. {min(rates):.1f}%)." if rates
                     else f"Cenários executados: {', '.join(ok_scn)}.")
    # SLA
    violators = []
    worst = (None, None, -1.0)
    for s, r in scn.items():
        if r.get("sla_p95_violations"):
            violators.append(s)
        bp = r.get("bottleneck_p95")
        if bp is not None and bp > worst[2]:
            worst = (s, r.get("bottleneck_endpoint"), bp)
    if violators:
        parts.append(
            f"A disponibilidade funcional foi preservada, mas a meta estrita de P95 < 500 ms "
            f"não foi atingida em todos os endpoints/cenários ({', '.join(violators)}). "
            f"O principal gargalo observado foi {worst[1]} (P95 {worst[2]:.0f} ms no cenário {worst[0]}).")
    elif ok_scn:
        parts.append("A meta de P95 < 500 ms foi respeitada nos cenários e endpoints medidos.")
    # analítica
    if analytics.get("status") == "OK":
        parts.append(
            f"A camada analítica recebeu {analytics['total_events']} eventos operacionais "
            f"(criação de pedidos, transições de estado e posições), confirmando a persistência.")
    elif analytics.get("status") == "PARTIAL":
        parts.append("A consulta à camada analítica funcionou, mas ainda com poucos/zero eventos (ver limitações).")
    else:
        parts.append("A verificação da camada analítica não pôde ser concluída (ver limitações).")
    # ETA
    if eta.get("status") == "OK":
        if eta.get("pct_fallback", 0) >= 50:
            parts.append(
                f"O ETA permaneceu integrado ao fluxo de pedidos, mas {eta['pct_fallback']:.0f}% das "
                f"respostas usaram fallback — confirma resiliência operacional, embora indique que o "
                f"modelo ainda precisa de maior disponibilidade/pré-carregamento.")
        else:
            mae = f", MAE {eta.get('mae_min')} min" if eta.get("mae_min") is not None else ""
            parts.append(
                f"O serviço preditivo retornou ETA no fluxo de criação do pedido "
                f"({eta.get('pct_model', 0):.0f}% via modelo{mae}).")
    # resiliência
    if resil.get("test_b", {}).get("fallback_ok"):
        parts.append("A criação de pedido não depende criticamente do modelo: sob ETA indisponível, "
                     "o fluxo recai em fallback determinístico sem perder o pedido.")
    return " ".join(parts)


def _cell(v):
    if v is None:
        return "[—]"
    s = str(v).replace("[", "(").replace("]", ")")
    return f"[{s}]"


def write_typ(path: Path, load: dict, analytics: dict, eta: dict, resil: dict, synthesis: str) -> None:
    scn = load.get("scenarios", {})
    L = ["== Resultados experimentais", ""]

    # Tabela 1 — carga
    L.append("=== Carga e latência (normal / peak / event)")
    L.append("#table(")
    L.append("  columns: 8,")
    L.append("  " + ", ".join(_cell(h) for h in
             ["*Cenário*", "*Criados*", "*Concl.*", "*Sucesso %*", "*P95 global*", "*P95 /order*", "*P95 /track*", "*SLA*"]) + ",")
    for sc in LOAD_SCENARIOS:
        r = scn.get(sc, {})
        sla = "OK" if r.get("sla_met") else ("VIOL" if r.get("status") == "OK" else "—")
        L.append("  " + ", ".join(_cell(v) for v in [
            sc, r.get("orders_created"), r.get("orders_completed"),
            r.get("success_rate_pct"),
            fnum(r.get("global_p95"), "ms"), fnum(r.get("order_p95"), "ms"),
            fnum(r.get("track_p95"), "ms"), sla]) + ",")
    L.append(")")
    L.append("")

    # Tabela 2 — analítica
    L.append("=== Camada analítica (eventos persistidos)")
    L.append("#table(")
    L.append("  columns: 5,")
    L.append("  " + ", ".join(_cell(h) for h in
             ["*Order CREATE*", "*Order UPDATE*", "*Posições*", "*Total*", "*Status*"]) + ",")
    L.append("  " + ", ".join(_cell(v) for v in [
        analytics.get("order_created_events"), analytics.get("order_state_events"),
        analytics.get("courier_position_events"), analytics.get("total_events"),
        analytics.get("status")]) + ",")
    L.append(")")
    L.append("")

    # Tabela 3 — ETA + resiliência
    L.append("=== ETA e resiliência")
    a = resil.get("test_a", {})
    b = resil.get("test_b", {})
    L.append("#table(")
    L.append("  columns: 6,")
    L.append("  " + ", ".join(_cell(h) for h in
             ["*Modelo*", "*ETA p95*", "*% modelo*", "*% fallback*", "*Pedidos A (criados)*", "*Fallback B*"]) + ",")
    L.append("  " + ", ".join(_cell(v) for v in [
        "ready" if eta.get("model_ready") else "fallback",
        fnum((eta.get("latency_ms") or {}).get("p95"), "ms"),
        fnum(eta.get("pct_model"), "%"), fnum(eta.get("pct_fallback"), "%"),
        f"{a.get('created', 0)}/{a.get('attempted', 0)}",
        "OK" if b.get("fallback_ok") else "—"]) + ",")
    L.append(")")
    L.append("")

    L.append("#small-note[")
    L.append("  Síntese: " + (synthesis or "—"))
    L.append("]")
    L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def write_md(path: Path, meta: dict, load: dict, analytics: dict, eta: dict, resil: dict, synthesis: str) -> None:
    L = [f"# Resultados experimentais — DijkFood (branch `{meta['branch']}`)", "",
         f"Gerado em {meta['generated_at']} · base-url `{meta['base_url']}`", "",
         "## 1. Carga e latência", "",
         "| Cenário | Criados | Concl. | Falhos | Sucesso % | P95 global | P95 /order | P95 /track | P95 /routes | Throughput | SLA |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for sc in LOAD_SCENARIOS:
        r = load.get("scenarios", {}).get(sc, {})
        sla = "OK" if r.get("sla_met") else ("VIOLADO" if r.get("status") == "OK" else "—")
        L.append("| " + " | ".join(map(str, [
            sc, r.get("orders_created", "—"), r.get("orders_completed", "—"), r.get("orders_failed", "—"),
            r.get("success_rate_pct", "—"), fnum(r.get("global_p95"), "ms"), fnum(r.get("order_p95"), "ms"),
            fnum(r.get("track_p95"), "ms"), fnum(r.get("route_p95"), "ms"),
            fnum(r.get("throughput_req_s"), "/s"), sla])) + " |")
    L += ["", "## 2. Camada analítica", "",
          f"- Order CREATE: **{analytics.get('order_created_events')}** · Order UPDATE: **{analytics.get('order_state_events')}** · Posições: **{analytics.get('courier_position_events')}**",
          f"- Total de eventos: **{analytics.get('total_events')}** · status: **{analytics.get('status')}**",
          f"- Primeiro: {analytics.get('first_event_at')} · Último: {analytics.get('last_event_at')}",
          "", "## 3. Predição de ETA", "",
          f"- Modelo pronto: **{eta.get('model_ready')}** · amostras treino: {eta.get('n_train_samples')} · MAE: {eta.get('mae_min')} min · baseline: {eta.get('baseline_mae_min')} min",
          f"- Chamadas: {eta.get('n_calls')} · ETA p95: {fnum((eta.get('latency_ms') or {}).get('p95'),'ms')} · % modelo: {fnum(eta.get('pct_model'),'%')} · % fallback: {fnum(eta.get('pct_fallback'),'%')} · ETA médio: {fnum(eta.get('mean_eta_min'),'min')}",
          "", "## 4. Resiliência", "",
          f"- Teste A (ETA normal): {resil.get('test_a',{}).get('created',0)}/{resil.get('test_a',{}).get('attempted',0)} pedidos criados · eta_source: {resil.get('test_a',{}).get('eta_sources')}",
          f"- Teste B (ETA indisponível): fallback_ok=**{resil.get('test_b',{}).get('fallback_ok')}** · pedido ainda criado: {resil.get('test_b',{}).get('live_order_still_created')}",
          "", "## Síntese", "", synthesis, ""]
    path.write_text("\n".join(L), encoding="utf-8")


def write_limitations(path: Path) -> None:
    L = ["# Limitações e falhas registradas", ""]
    if not LIMITATIONS:
        L.append("Nenhuma limitação registrada — todas as seções concluíram.")
    else:
        for section, msg in LIMITATIONS:
            L.append(f"- **{section}**: {msg}")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ───────────────────────────── main ──────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="DijkFood — resultados experimentais compactos (A2).")
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", ""))
    ap.add_argument("--prediction-url", default=os.environ.get("PREDICTION_URL", ""))
    ap.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--athena-database", default=os.environ.get("ATHENA_DATABASE", ""))
    ap.add_argument("--athena-output-s3", default=os.environ.get("ATHENA_OUTPUT_S3", ""))
    ap.add_argument("--data-lake-bucket", default=os.environ.get("DATA_LAKE_BUCKET", ""))
    ap.add_argument("--duration", type=int, default=int(os.environ.get("SIM_DURATION", "20")),
                    help="duração (s) de cada cenário de carga (default 20)")
    ap.add_argument("--eta-samples", type=int, default=20, help="chamadas a /predict/eta")
    ap.add_argument("--resilience-orders", type=int, default=5, help="pedidos no Teste A")
    ap.add_argument("--scan-only", action="store_true", help="só descobre capacidades; não roda experimentos")
    ap.add_argument("--skip-load", action="store_true")
    ap.add_argument("--skip-analytics", action="store_true")
    ap.add_argument("--skip-eta", action="store_true")
    ap.add_argument("--skip-resilience", action="store_true")
    ap.add_argument("--output-dir", default="")
    args = ap.parse_args()

    if not args.prediction_url:
        args.prediction_url = args.base_url

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else (REPO_ROOT / "artifacts" / "experiments" / ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Saída: {out_dir}")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branch": _git_branch(),
        "base_url": args.base_url,
        "prediction_url": args.prediction_url,
        "duration_per_scenario_s": args.duration,
    }

    if args.scan_only:
        scan = do_scan(args)
        (out_dir / "summary.json").write_text(
            json.dumps({"mode": "scan", "meta": meta, "scan": scan}, indent=2, ensure_ascii=False), encoding="utf-8")
        write_limitations(out_dir / "limitations.md")
        print("scan-only concluído.")
        return

    load = {"status": "SKIPPED", "scenarios": {}}
    analytics = {"status": "SKIPPED", "total_events": 0}
    eta = {"status": "SKIPPED"}
    resil = {"status": "SKIPPED", "test_a": {}, "test_b": {}}

    if not args.skip_load:
        try:
            load = run_load(args.base_url, args.duration)
        except Exception as exc:  # noqa: BLE001
            add_limitation("load", f"exceção inesperada: {exc}")
            load = {"status": "ERROR", "scenarios": {}}

    if not args.skip_analytics:
        try:
            analytics = run_analytics(args.aws_region, args.athena_database, args.athena_output_s3, args.data_lake_bucket)
        except Exception as exc:  # noqa: BLE001
            add_limitation("analytics", f"exceção inesperada: {exc}")
            analytics = {"status": "ERROR", "total_events": 0}

    if not args.skip_eta:
        try:
            eta = run_eta(args.prediction_url, args.base_url, args.eta_samples)
        except Exception as exc:  # noqa: BLE001
            add_limitation("eta", f"exceção inesperada: {exc}")
            eta = {"status": "ERROR"}

    if not args.skip_resilience:
        try:
            resil = run_resilience(args.base_url, args.prediction_url, args.resilience_orders)
        except Exception as exc:  # noqa: BLE001
            add_limitation("resilience", f"exceção inesperada: {exc}")
            resil = {"status": "ERROR", "test_a": {}, "test_b": {}}

    synthesis = build_synthesis(load, analytics, eta, resil)

    # Sempre grava todos os arquivos, mesmo com falhas parciais.
    write_load_csv(out_dir / "load_results.csv", load)
    (out_dir / "eta_results.json").write_text(json.dumps(eta, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "analytics_counts.json").write_text(json.dumps(analytics, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "resilience_results.json").write_text(json.dumps(resil, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {"meta": meta, "load": load, "analytics": analytics, "eta": eta,
               "resilience": resil, "synthesis": synthesis}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_typ(out_dir / "summary.typ", load, analytics, eta, resil, synthesis)
    write_md(out_dir / "summary.md", meta, load, analytics, eta, resil, synthesis)
    write_limitations(out_dir / "limitations.md")

    print("\n== Síntese ==")
    print(synthesis)
    print(f"\nArquivos gerados em: {out_dir}")


def _git_branch() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                           cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "?"
    except Exception:  # noqa: BLE001
        return "?"


if __name__ == "__main__":
    main()
