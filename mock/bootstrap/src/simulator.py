"""
DijkFood - Simulador de Carga e Ciclo de Vida
=================================================

Uso:
  python simulator.py                 # cenário padrão (10 req/s)
  SCENARIO=peak python simulator.py   # 50 req/s
  SCENARIO=event python simulator.py  # 200 req/s
"""

import asyncio
import random
import os
import logging
import time
import statistics
import httpx
import sys
from datetime import datetime

from dotenv import load_dotenv
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from utils import get_random_sp_coordinate

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("simulator")
log.addHandler(logging.StreamHandler(sys.stdout))

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
load_dotenv()
BASE_URL = os.getenv("BASE_URL", "")
if BASE_URL == "":
    CRUD_URL      = os.getenv("CRUD_URL",      "http://localhost:8000")
    ORDER_URL     = os.getenv("ORDER_URL",     "http://localhost:8001")
    TRACKING_URL  = os.getenv("TRACKING_URL",  "http://localhost:8002")
    ROUTE_URL     = os.getenv("ROUTE_URL",     "http://localhost:8003")
else:
    CRUD_URL      = BASE_URL
    ORDER_URL     = BASE_URL
    TRACKING_URL  = BASE_URL
    ROUTE_URL     = BASE_URL

class OrderState(int, Enum):
    CONFIRMED        = 1
    PREPARING        = 2
    READY_FOR_PICKUP = 3
    PICKED_UP        = 4
    IN_TRANSIT       = 5
    DELIVERED        = 6

SILENT = os.getenv("SILENT", "false").lower() in ("true", "1", "yes")

@dataclass
class SimConfig:
    scenario: str = os.getenv("SCENARIO", "testing")
    orders_per_second: float = 0.0
    duration_seconds: int = int(os.getenv("SIM_DURATION", 10))
    position_report_interval: float = float(os.getenv("POSITION_INTERVAL", 0.1)) # 100ms exigido
    delay_preparing_min: float = float(os.getenv("DELAY_PREPARING_MIN", 5.0))
    delay_preparing_max: float = float(os.getenv("DELAY_PREPARING_MAX", 10.0))
    delay_ready_min: float = float(os.getenv("DELAY_READY_MIN", 5.0))
    delay_ready_max: float = float(os.getenv("DELAY_READY_MAX", 10.0))
    tracking_lifetime: float = float(os.getenv("TRACKING_LIFETIME", 5.0))
    max_concurrent_orders: int = int(os.getenv("SIM_CONCURRENCY", 1000))
    max_retries: int = int(os.getenv("SIM_MAX_RETRIES", 5))
    silent: bool = os.getenv("SILENT", "false").lower() in ("true", "1", "yes")

    # ── Cenários operacionais parametrizáveis (A2) ──
    # Concentração de demanda numa região (célula H3 do restaurante).
    hotspot_region: str = os.getenv("HOTSPOT_REGION", "")
    hotspot_weight: float = float(os.getenv("HOTSPOT_WEIGHT", 0.0))  # fração de pedidos direcionados à região
    # Concentração de pedidos em poucos restaurantes "quentes".
    restaurant_concentration: float = float(os.getenv("RESTAURANT_CONCENTRATION", 0.0))  # fração de pedidos
    hot_restaurant_count: int = int(os.getenv("HOT_RESTAURANT_COUNT", 5))
    # Redução temporária da disponibilidade de entregadores.
    courier_outage_pct: float = float(os.getenv("COURIER_OUTAGE_PCT", 0.0))  # 0..1

    def __post_init__(self):
        # Cenários de volume (A1) + presets de cenário operacional (A2).
        scenarios_mapping = {
            "testing": 5.0,
            "normal": 10.0,
            "peak": 50.0,
            "event": 200.0,
            # presets A2 — herdam volume "peak" e ligam o respectivo knob
            "hotspot": 50.0,
            "concentration": 50.0,
            "outage": 50.0,
        }
        self.orders_per_second = scenarios_mapping.get(self.scenario, self.orders_per_second)

        # Presets convenientes: ativam o knob se o usuário não o definiu explicitamente.
        if self.scenario == "hotspot" and self.hotspot_weight == 0.0:
            self.hotspot_weight = 0.7
        if self.scenario == "concentration" and self.restaurant_concentration == 0.0:
            self.restaurant_concentration = 0.8
        if self.scenario == "outage" and self.courier_outage_pct == 0.0:
            self.courier_outage_pct = 0.6

# ---------------------------------------------------------------------------
# Métricas Granulares
# ---------------------------------------------------------------------------

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

        # ── Sumário global de SLA (evidência de não-regressão) ──
        all_lat = [r["latency_ms"] for r in self.records]
        total = len(self.records)
        http_errors = sum(1 for r in self.records if r["status"] >= 400)
        net_errors = sum(1 for r in self.records if r["status"] == 0)
        success = sum(1 for r in self.records if r["status"] in (200, 201))
        if len(all_lat) >= 2:
            gq = statistics.quantiles(all_lat, n=100)
            g_p50, g_p90, g_p95 = gq[49], gq[89], gq[94]
        else:
            g_p50 = g_p90 = g_p95 = all_lat[0]
        print(f"SLA GLOBAL | reqs: {total} | sucesso: {success} "
              f"({100*success/total:.1f}%) | erros HTTP: {http_errors} | erros rede/timeout: {net_errors} "
              f"| taxa de erro: {100*(http_errors+net_errors)/total:.2f}%")
        print(f"Latência global | P50: {g_p50:.1f}ms | P90: {g_p90:.1f}ms | P95: {g_p95:.1f}ms "
              f"(requisito P95 < 500ms)")
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
            by_endpoint.setdefault(key, []).append(r["latency_ms"])

        print(f"{'ENDPOINT':<33s} | {'COUNT':<6s} | {'AVG':<7s} | {'P50':<7s} | {'P90':<7s} | {'P95 (Req P95<500ms)':<19s}")
        print("-" * 92)
        for key, latencies in sorted(by_endpoint.items()):
            n = len(latencies)
            avg = sum(latencies) / n
            if len(latencies) >= 2:
                quantiles = statistics.quantiles(latencies, n=100)
                p50 = quantiles[49]
                p90 = quantiles[89]
                p95 = quantiles[94]
            else:
                p50 = p90 = p95 = latencies[0]
            # Alerta visual se passar de 500ms
            p95_str = f"{p95:6.1f}ms" + (" [!]" if p95 > 500 else "    ")
            print(f"{key:<33s} | {n:<6d} | {avg:5.1f}ms | {p50:5.1f}ms | {p90:5.1f}ms | {p95_str:<19s}")
        print("=" * 92)

metrics = Metrics()

# ---------------------------------------------------------------------------
# Helpers HTTP & Lógica de Negócio
# ---------------------------------------------------------------------------

async def _request(
    client: httpx.AsyncClient, method: str, base_url: str, path: str, sem: asyncio.Semaphore, config: SimConfig, **kwargs
):
    url = f"{base_url}{path}"
    
    for attempt in range(1, config.max_retries + 1):
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.request(method, url, **kwargs)
                latency = (time.perf_counter() - t0) * 1000
                
                # Registra latência apenas de requisições concluídas
                metrics.record_latency(path, method, latency, resp.status_code)
                
                if resp.status_code in (200, 201):
                    try: return resp.json()
                    except: return {}
                return None
                
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                # Apenas incrementa erro, evita sujar estatísticas com tempo de timeout local
                metrics.errors += 1
                
        if attempt < config.max_retries:
            await asyncio.sleep(0.3 * (2 ** (attempt - 1)))
            
    return None

async def fetch_route(client, sem, config, orig_lat, orig_lon, dest_lat, dest_lon):
    payload = {
        "orig_lat": orig_lat, "orig_lon": orig_lon, 
        "dest_lat": dest_lat, "dest_lon": dest_lon
    }
    body = await _request(client, "POST", ROUTE_URL, "/routes/calculate", sem, config, json=payload)
    if body:
        return body.get("path_nodes", [])
    
    # Fallback de interpolação
    return [(orig_lat + (dest_lat - orig_lat) * i / 5, orig_lon + (dest_lon - orig_lon) * i / 5) for i in range(6)]

# ---------------------------------------------------------------------------
# Ciclo de Vida do Pedido
# ---------------------------------------------------------------------------

async def run_order_lifecycle(client: httpx.AsyncClient, sem: asyncio.Semaphore, user_id: int, restaurant_id: int, config: SimConfig):
    # 1. Criação
    body = await _request(client, "POST", ORDER_URL, "/order", sem, config, json={"id_user": user_id, "id_restaurant": restaurant_id})
    if not body or "id_order" not in body:
        metrics.orders_not_created += 1
        log.warning(f"Falha ao criar pedido para usuário {user_id} e restaurante {restaurant_id}.")
        return

    order_id = body["id_order"]
    courier_id = body.get("id_courier")
    metrics.orders_created += 1

    # Busca coordenadas no CRUD (em paralelo)
    u_task = _request(client, "GET", CRUD_URL, f"/users/{user_id}", sem, config)
    r_task = _request(client, "GET", CRUD_URL, f"/restaurants/{restaurant_id}", sem, config)
    user_data, rest_data = await asyncio.gather(u_task, r_task)
    
    if rest_data:
        o_lat, o_lon = (float(rest_data["lat"]), float(rest_data["lon"]))
    else:
        metrics.orders_failed += 1
        log.warning(f"Coordenadas do restaurante {restaurant_id} não encontradas para pedido {order_id}. Finalizando execução sem simular rota.")
        return
    if user_data:
        d_lat, d_lon = (float(user_data["lat"]), float(user_data["lon"]))
    else:
        metrics.orders_failed += 1
        log.warning(f"Coordenadas do usuário {user_id} não encontradas para pedido {order_id}. Finalizando execução sem simular rota.")
        return
    
    # 2. Busca Rota (Entregador -> Restaurante -> Cliente)
    waypoints = await fetch_route(client, sem, config, o_lat, o_lon, d_lat, d_lon)

    if not (isinstance(waypoints, list) and len(waypoints) > 0):
        log.warning(f"Rota falhou para pedido {order_id}. Finalizando execução sem simular rota.")
        log.warning(waypoints)
        return
    
    # 3. Transições com Delays
    async def advance(state: OrderState):
        result = await _request(client, "PATCH", ORDER_URL, "/order", sem, config, json={"id_order": order_id, "id_state": state.value})
        if result and result.get('id_state', None) == state.value:
            return True
        else:
            return False
    
    ## Estado 1 -> 2 (CONFIRMED -> PREPARING)
    await asyncio.sleep(random.uniform(config.delay_preparing_min, config.delay_preparing_max))
    result = await advance(OrderState.PREPARING)
    if not result:
        metrics.orders_failed += 1
        log.warning(f"Falha ao avançar para PREPARING no pedido {order_id}. Finalizando execução sem simular rota.")
        return
    ## Estado 2 -> 3 (PREPARING -> READY_FOR_PICKUP)
    await asyncio.sleep(random.uniform(config.delay_ready_min, config.delay_ready_max))
    result = await advance(OrderState.READY_FOR_PICKUP)
    if not result:
        metrics.orders_failed += 1
        log.warning(f"Falha ao avançar para READY_FOR_PICKUP no pedido {order_id}. Finalizando execução sem simular rota.")
        return
    ## Estado 3 -> 4 (READY_FOR_PICKUP -> PICKED_UP)
    await asyncio.sleep(5.0)
    result = await advance(OrderState.PICKED_UP)
    if not result:
        metrics.orders_failed += 1
        log.warning(f"Falha ao avançar para PICKED_UP no pedido {order_id}. Finalizando execução sem simular rota.")
        return
    # Estado 4 -> 5 (PICKED_UP -> IN_TRANSIT)
    await asyncio.sleep(0.1)
    result = await advance(OrderState.IN_TRANSIT)
    if not result:
        metrics.orders_failed += 1
        log.warning(f"Falha ao avançar para IN_TRANSIT no pedido {order_id}. Finalizando execução sem simular rota.")
        return

    # 4. Tracking a cada 100ms (Req. Não-Funcional)
    if courier_id:
        # Limita o tempo da simulação de rota para aproximadamente 5s, mesmo que a rota tenha muitos pontos
        limit_time = int(config.tracking_lifetime / config.position_report_interval)
        if(len(waypoints) > limit_time): 
            step = len(waypoints) // limit_time
            waypoints = waypoints[::step] + [waypoints[-1]]
        elif len(waypoints) < limit_time and len(waypoints) > 0:
            # Repete o último waypoint até preencher o limit_time esperado
            needed = limit_time - len(waypoints)
            waypoints = waypoints + [waypoints[-1]] * needed

        for wp_lat, wp_lon in waypoints:
            await _request(client, "POST", TRACKING_URL, "/tracking/position", sem, config, json={
                "ID_courier": courier_id, "lat": wp_lat, "lon": wp_lon
            })
            await asyncio.sleep(config.position_report_interval)

    # 5. Estado Final (IN_TRANSIT -> DELIVERED)
    result = await advance(OrderState.DELIVERED)
    if not result:
        metrics.orders_failed += 1
        log.warning(f"Falha ao avançar para DELIVERED no pedido {order_id}.")
        return
    metrics.orders_completed += 1

# ---------------------------------------------------------------------------
# Emissor e Bootstrap
# ---------------------------------------------------------------------------

async def fetch_existing_ids(client: httpx.AsyncClient, sem: asyncio.Semaphore, config: SimConfig):
    users = []
    rests = []
    rests_meta = []  # [{id, h3}] — usado pelos cenários (hotspot/concentração)
    MAX_PAGES = 100 # Limite para evitar loops infinitos em caso de falhas no endpoint
    page = 1
    while page <= MAX_PAGES:
        u_body = await _request(client, "GET", CRUD_URL, f"/users?page={page}&itemsPerPage=500", sem, config)
        if u_body:
            users.extend([u["id_user"] for u in u_body.get("data", [])])
            if u_body['has_more']:
                page += 1
            else:
                break
        else:
            break

    page = 1
    while page <= MAX_PAGES:
        r_body = await _request(client, "GET", CRUD_URL, f"/restaurants?page={page}&itemsPerPage=500", sem, config)
        if r_body:
            for r in r_body.get("data", []):
                rests.append(r["id_restaurant"])
                rests_meta.append({"id": r["id_restaurant"], "h3": r.get("h3_index")})
            if r_body['has_more']:
                page += 1
            else:
                break
        else:
            break

    return users, rests, rests_meta


# ---------------------------------------------------------------------------
# Cenários operacionais parametrizáveis (A2)
# ---------------------------------------------------------------------------

def build_restaurant_population(rests_meta: list, config: SimConfig):
    """Constrói (população, pesos) para amostragem ponderada dos restaurantes
    conforme os knobs de cenário (hotspot por região e concentração)."""
    ids = [m["id"] for m in rests_meta]
    if not ids:
        return ids, None

    weights = [1.0] * len(ids)

    # (a) Hotspot por região: direciona `hotspot_weight` da massa de pedidos
    #     para os restaurantes da região alvo.
    if config.hotspot_region and 0.0 < config.hotspot_weight < 1.0:
        target_idx = [i for i, m in enumerate(rests_meta) if str(m.get("h3")) == str(config.hotspot_region)]
        if target_idx:
            others_idx = [i for i in range(len(ids)) if i not in set(target_idx)]
            w_target = config.hotspot_weight / len(target_idx)
            w_other = (1.0 - config.hotspot_weight) / max(1, len(others_idx))
            for i in target_idx:
                weights[i] = w_target
            for i in others_idx:
                weights[i] = w_other
            log.info(f"[cenário] hotspot região {config.hotspot_region}: "
                     f"{len(target_idx)} restaurantes recebendo {config.hotspot_weight:.0%} da demanda")
        else:
            log.warning(f"[cenário] nenhum restaurante na região {config.hotspot_region} — hotspot ignorado")

    # (b) Concentração: `restaurant_concentration` da massa em `hot_restaurant_count` restaurantes.
    elif 0.0 < config.restaurant_concentration < 1.0:
        k = min(config.hot_restaurant_count, len(ids))
        hot_idx = set(random.sample(range(len(ids)), k))
        cold_idx = [i for i in range(len(ids)) if i not in hot_idx]
        w_hot = config.restaurant_concentration / k
        w_cold = (1.0 - config.restaurant_concentration) / max(1, len(cold_idx))
        for i in range(len(ids)):
            weights[i] = w_hot if i in hot_idx else w_cold
        log.info(f"[cenário] concentração: {k} restaurantes recebendo "
                 f"{config.restaurant_concentration:.0%} da demanda")

    return ids, weights


async def apply_courier_outage(client: httpx.AsyncClient, sem: asyncio.Semaphore, config: SimConfig):
    """Reduz temporariamente a disponibilidade de entregadores marcando uma
    fração deles como OFFLINE (simula indisponibilidade)."""
    if not (0.0 < config.courier_outage_pct < 1.0):
        return

    couriers = []
    page = 1
    while True:
        body = await _request(client, "GET", CRUD_URL, f"/couriers?page={page}&itemsPerPage=500", sem, config)
        if body:
            couriers.extend([c["id_courier"] for c in body.get("data", [])])
            if body.get("has_more"):
                page += 1
            else:
                break
        else:
            break

    if not couriers:
        log.warning("[cenário] sem entregadores para aplicar outage")
        return

    n_off = int(len(couriers) * config.courier_outage_pct)
    offline = random.sample(couriers, n_off)
    tasks = [
        _request(client, "PATCH", TRACKING_URL, "/tracking/status", sem, config,
                 json={"ID_courier": cid, "status": "OFFLINE"})
        for cid in offline
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info(f"[cenário] outage: {n_off}/{len(couriers)} entregadores marcados OFFLINE "
             f"({config.courier_outage_pct:.0%})")

async def order_emitter(client, users, restaurants, config, weights=None):
    sem = asyncio.Semaphore(config.max_concurrent_orders)
    interval = 1.0 / config.orders_per_second
    end_time = time.perf_counter() + config.duration_seconds
    tasks = set()

    def _on_order_done(task: asyncio.Task):
        tasks.discard(task)
        metrics.max_simultaneous_orders = max(metrics.max_simultaneous_orders, len(tasks))
        log.info(f"Pedidos em andamento restantes: {len(tasks)}")
        print(f"Pedidos em andamento restantes: {len(tasks)}")

    while time.perf_counter() < end_time:
        t_start = time.perf_counter()

        u_id = random.choice(users)
        # Amostragem ponderada quando há cenário de hotspot/concentração.
        if weights is not None:
            r_id = random.choices(restaurants, weights=weights, k=1)[0]
        else:
            r_id = random.choice(restaurants)

        task = asyncio.create_task(run_order_lifecycle(client, sem, u_id, r_id, config))
        tasks.add(task)
        task.add_done_callback(_on_order_done)

        sleep_for = max(0.0, interval - (time.perf_counter() - t_start))
        await asyncio.sleep(sleep_for)

    if tasks:
        log.info(f"Fim da emissão. Aguardando {len(tasks)} pedidos em andamento...")
        await asyncio.gather(*list(tasks), return_exceptions=True)

async def main():
    config = SimConfig()
    sim_start = time.perf_counter()

    if config.silent:
        logging.getLogger("httpx").setLevel(logging.ERROR)

    print("Iniciando cenario:", config.scenario, "as", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    limits = httpx.Limits(max_connections=config.max_concurrent_orders + 50, max_keepalive_connections=config.max_concurrent_orders)
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        sem_init = asyncio.Semaphore(10)
        users, restaurants, rests_meta = await fetch_existing_ids(client, sem_init, config)

        if not users or not restaurants:
            log.error("Banco vazio! Rode o populate.py antes.")
            return

        log.info(f"Carregados {len(users)} usuários e {len(restaurants)} restaurantes.")

        # Cenários operacionais (A2): população ponderada + outage de entregadores.
        population, weights = build_restaurant_population(rests_meta, config)
        await apply_courier_outage(client, sem_init, config)

        await order_emitter(client, users, population or restaurants, config, weights=weights)

    total_duration = time.perf_counter() - sim_start
    metrics.report(config, total_duration)

if __name__ == "__main__":
    print(BASE_URL)
    asyncio.run(main())
