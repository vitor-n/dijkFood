import time
import statistics
from dataclasses import dataclass, field
from typing import Optional
from config import SimConfig

try:
    import matplotlib.pyplot as plt
    HAS_PLOT = True
except ImportError:
    HAS_PLOT = False

@dataclass
class Metrics:
    records: list = field(default_factory=list)
    orders_created: int = 0
    orders_not_created: int = 0
    orders_completed: int = 0
    orders_failed: int = 0
    errors: int = 0
    max_simultaneous_orders: int = 0

    def record_latency(self, endpoint: str, method: str, latency_ms: float, status: int):
        self.records.append({
            "timestamp": time.time(),
            "endpoint": endpoint,
            "method": method,
            "latency_ms": latency_ms,
            "status": status
        })

    def report(self, config: SimConfig, duration_seconds: Optional[float] = None):
        print("=" * 80)
        print(f"RELATÓRIO DO SIMULADOR | Cenário: {config.scenario.upper()} ({config.orders_per_second} req/s)")
        if duration_seconds is not None:
            print(f"Tempo total desde o início até finalizar: {duration_seconds:.1f}s")
        print(f"Pedidos: {self.orders_created} criados | {self.orders_completed} concluídos | {self.orders_failed} falhos")
        print(f"Pedidos não criados: {self.orders_not_created}")
        print(f"Máximo de pedidos simultâneos: {self.max_simultaneous_orders}")
        print(f"Erros de rede/timeout: {self.errors}")
        print("=" * 80)
        
        if not self.records:
            print("Nenhuma métrica de rede coletada.")
            return

        # - Sumário global de SLA (evidência de não-regressão) -
        all_lat = [r["latency_ms"] for r in self.records]
        total = len(self.records)
        http_errors = sum(1 for r in self.records if r["status"] >= 400)
        net_errors = sum(1 for r in self.records if r["status"] == 0)
        success = sum(1 for r in self.records if r["status"] in (200, 201))
        if len(all_lat) >= 2:
            gq = statistics.quantiles(all_lat, n=100)
            g_p50, g_p90, g_p95, g_p99 = gq[49], gq[89], gq[94], gq[98]
        else:
            g_p50 = g_p90 = g_p95 = g_p99 = all_lat[0]
        print(f"SLA GLOBAL | reqs: {total} | sucesso: {success} "
              f"({100*success/total:.1f}%) | erros HTTP: {http_errors} | erros rede/timeout: {net_errors} "
              f"| taxa de erro: {100*(http_errors+net_errors)/total:.2f}%")
        print(f"Latência global | P50: {g_p50:.1f}ms | P90: {g_p90:.1f}ms | P95: {g_p95:.1f}ms "
              f"| P99: {g_p99:.1f}ms (requisito P95 < 500ms)")
        print("=" * 80)

        by_endpoint: dict = {}
        for r in self.records:
            # Agrupa endpoints parametrizados para o log ficar limpo
            ep = r["endpoint"]

            if "/users?page" in ep: ep = "/users?page={X}"
            elif "/users/" in ep: ep = "/users/{id}"
            elif "/restaurants?page" in ep: ep = "/restaurants?page={X}"
            elif "/restaurants/" in ep: ep = "/restaurants/{id}"
            
            key = f"{r['method']} {ep}"
            by_endpoint.setdefault(key, []).append(r)

        print(f"{'ENDPOINT':<33s} | {'COUNT':<6s} | {'AVG':<7s} | {'P50':<7s} | {'P90':<7s} | {'P95':<7s} | {'P99 (Req P95<500ms)':<19s}")
        print("-" * 104)
        for key, records in sorted(by_endpoint.items()):
            latencies = [r["latency_ms"] for r in records]
            n = len(latencies)
            avg = sum(latencies) / n
            if len(latencies) >= 2:
                quantiles = statistics.quantiles(latencies, n=100)
                p50 = quantiles[49]
                p90 = quantiles[89]
                p95 = quantiles[94]
                p99 = quantiles[98]
            else:
                p50 = p90 = p95 = p99 = latencies[0]
            # Alerta visual se passar de 500ms
            p99_str = f"{p99:6.1f}ms" + (" [!]" if p95 > 500 else "    ")
            print(f"{key:<33s} | {n:<6d} | {avg:5.1f}ms | {p50:5.1f}ms | {p90:5.1f}ms | {p95:5.1f}ms | {p99_str:<19s}")
        print("=" * 92)

        if config.plot_metrics:
            self.plot_latency_over_time(by_endpoint, config)

    def plot_latency_over_time(self, by_endpoint: dict, config: SimConfig):
        if not HAS_PLOT:
            print("[Aviso] PLOT_METRICS ativado, mas matplotlib não está instalado. Pulei o gráfico.")
            return

        if not self.records:
            return

        # Encontra o tempo inicial
        t_min = min(r["timestamp"] for r in self.records)

        plt.figure(figsize=(12, 6))

        for key, records in sorted(by_endpoint.items()):
            if len(records) < 2:
                continue
            
            # Ignorar rotas de carga inicial para não poluir o plot
            if "GET /users?page=" in key or "GET /restaurants?page=" in key:
                continue

            # Agrupa as latências por segundo (em relação ao início)
            sec_map = {}
            for r in records:
                sec = int(r["timestamp"] - t_min)
                sec_map.setdefault(sec, []).append(r["latency_ms"])

            # Calcula a média por segundo
            secs = sorted(sec_map.keys())
            avgs = [sum(sec_map[s]) / len(sec_map[s]) for s in secs]

            color = None
            if "PATCH /order" in key:
                color = "red"
            elif "POST /tracking/position" in key:
                color = "blue"

            if color:
                plt.plot(secs, avgs, marker='.', label=key, color=color)
            else:
                plt.plot(secs, avgs, marker='.', label=key)

        plt.title(f'Evolução da Latência Média por Segundo ({config.orders_per_second} req/s, {config.duration_seconds}s)')
        plt.xlabel('Tempo (segundos)')
        plt.ylabel('Latência Média (ms)')
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        
        from datetime import datetime
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"plots/latency_plot_{config.orders_per_second}reqs_{config.duration_seconds}s_{timestamp_str}.png"
        
        plt.savefig(filename)
        print(f"Gráfico de latência salvo em '{filename}'.")

metrics = Metrics()
