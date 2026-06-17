"""
bench_dashboard.py — mede a latência do endpoint de dados do dashboard.

Evidência experimental do Conserto #1 (Arquitetura Lambda): comparar a latência
de /dashboard/api/data ANTES (varredura de 30 dias de JSON cru) e DEPOIS (marts
Parquet + speed overlay). Roda só com a stdlib.

Uso:
  DASHBOARD_URL=http://<host>/dashboard/api/data python mock/bench_dashboard.py
  DASHBOARD_URL=... BENCH_N=30 python mock/bench_dashboard.py

Reporta a primeira amostra (COLD, cache vazio) e a distribuição das demais
(P50/P95/P99). Lembre que o servidor tem cache server-side (CACHE_TTL): as
amostras quentes refletem o cache; a COLD reflete a query real no Athena.
"""
import os
import statistics
import time
import urllib.request

URL = os.getenv("DASHBOARD_URL", "http://localhost/dashboard/api/data")
N = int(os.getenv("BENCH_N", "20"))
TIMEOUT = float(os.getenv("BENCH_TIMEOUT", "60"))


def _one() -> tuple[float, int]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(URL, headers={"Cache-Control": "no-store"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read()
            status = resp.status
    except Exception as exc:  # noqa: BLE001
        print(f"  ! falha: {exc}")
        status = 0
    return (time.perf_counter() - t0) * 1000, status


def main() -> None:
    print("=" * 72)
    print(f"BENCH dashboard | {URL} | {N} amostras")
    print("=" * 72)

    cold_ms, cold_status = _one()
    print(f"COLD (1ª req, cache vazio): {cold_ms:.0f} ms | HTTP {cold_status}")

    samples = []
    for i in range(N):
        ms, status = _one()
        samples.append(ms)
        print(f"  req {i+1:>2}/{N}: {ms:7.0f} ms | HTTP {status}")

    ok = [s for s in samples if s > 0]
    if len(ok) >= 2:
        q = statistics.quantiles(ok, n=100)
        p50, p95, p99 = q[49], q[94], q[98]
    elif ok:
        p50 = p95 = p99 = ok[0]
    else:
        print("Sem amostras válidas.")
        return

    print("-" * 72)
    print(f"COLD: {cold_ms:.0f} ms | "
          f"WARM → P50: {p50:.0f} ms · P95: {p95:.0f} ms · P99: {p99:.0f} ms "
          f"· min: {min(ok):.0f} · max: {max(ok):.0f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
