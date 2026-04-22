"""
DijkFood - Simulador de Carga e Ciclo de Vida
=================================================
Versão Final: Combina os endpoints corretos de microsserviços com a 
emissão cadenciada, delays realistas e métricas granulares por rota.

Uso:
  python load_simulator.py                 # cenário padrão (10 req/s)
  SCENARIO=peak python load_simulator.py   # 50 req/s
  SCENARIO=event python load_simulator.py  # 200 req/s
"""

import asyncio
import random
import os
import logging
import time
import statistics
import httpx

from dotenv import load_dotenv
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from utils import get_random_sp_coordinate

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("simulator")

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

@dataclass
class SimConfig:
    scenario: str = os.getenv("SCENARIO", "normal")
    orders_per_second: float = 0.0
    duration_seconds: int = int(os.getenv("SIM_DURATION", 10))
    position_report_interval: float = float(os.getenv("POSITION_INTERVAL", 0.1)) # 100ms exigido
    delay_preparing_min: float = float(os.getenv("DELAY_PREPARING_MIN", 1.0))
    delay_preparing_max: float = float(os.getenv("DELAY_PREPARING_MAX", 3.0))
    delay_ready_min: float = float(os.getenv("DELAY_READY_MIN", 1.0))
    delay_ready_max: float = float(os.getenv("DELAY_READY_MAX", 5.0))
    max_concurrent_orders: int = int(os.getenv("SIM_CONCURRENCY", 1000))
    max_retries: int = int(os.getenv("SIM_MAX_RETRIES", 5))

    def __post_init__(self):
        scenarios_mapping = {
            "testing": 10.0,
            "normal": 10.0,
            "peak": 50.0,
            "event": 200.0
        }
        self.orders_per_second = scenarios_mapping.get(self.scenario, self.orders_per_second)

# ---------------------------------------------------------------------------
# Métricas Granulares (Para provar isolamento)
# ---------------------------------------------------------------------------

@dataclass
class Metrics:
    records: list = field(default_factory=list)
    orders_created: int = 0
    orders_completed: int = 0
    orders_failed: int = 0
    errors: int = 0

    def record_latency(self, endpoint: str, method: str, latency_ms: float, status: int):
        self.records.append({
            "endpoint": endpoint,
            "method": method,
            "latency_ms": latency_ms,
            "status": status
        })

    def report(self, config: SimConfig):
        log.info("=" * 80)
        log.info(f"RELATÓRIO DO SIMULADOR | Cenário: {config.scenario.upper()} ({config.orders_per_second} req/s)")
        log.info(f"Pedidos: {self.orders_created} criados | {self.orders_completed} concluídos | {self.orders_failed} falhos")
        log.info(f"Erros de rede/timeout: {self.errors}")
        log.info("=" * 80)
        
        if not self.records:
            log.info("Nenhuma métrica de rede coletada.")
            return
            
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

        log.info(f"{'ENDPOINT':<35s} | {'COUNT':<6s} | {'AVG':<6s} | {'P50':<6s} | {'P95 (Req: <500ms)':<17s}")
        log.info("-" * 80)
        for key, latencies in sorted(by_endpoint.items()):
            n = len(latencies)
            avg = sum(latencies) / n
            if(len(latencies) >= 2):
                quantiles = statistics.quantiles(latencies, n=100)
                p50 = quantiles[49]
                p95 = quantiles[94]
            else:
                p50 = latencies[0]
                p95 = latencies[0]     
            # Alerta visual se passar de 500ms
            p95_str = f"{p95:7.1f}ms"
            if p95 > 500: p95_str += " ⚠️"
            
            log.info(f"{key:<35s} | {n:<6d} | {avg:5.1f}ms | {p50:5.1f}ms | {p95_str}")
        log.info("=" * 80)

metrics = Metrics()

# ---------------------------------------------------------------------------
# Helpers HTTP & Lógica de Negócio
# ---------------------------------------------------------------------------

async def _request(
    client: httpx.AsyncClient, method: str, base_url: str, path: str, sem: asyncio.Semaphore, config: SimConfig, **kwargs
):
    """Executa requisição com Retry, medindo latência exata."""
    url = f"{base_url}{path}"
    
    for attempt in range(1, config.max_retries + 1):
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.request(method, url, **kwargs)
                latency = (time.perf_counter() - t0) * 1000
                metrics.record_latency(path, method, latency, resp.status_code)
                
                if resp.status_code in (200, 201):
                    try: return resp.json()
                    except: return {}
                else:
                    return None
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                latency = (time.perf_counter() - t0) * 1000
                metrics.record_latency(path, method, latency, 0)
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
        metrics.orders_failed += 1
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
        aux = get_random_sp_coordinate()
        o_lat, o_lon = (float(aux["lat"]), float(aux["lon"]))

    if user_data:
        d_lat, d_lon = (float(user_data["lat"]), float(user_data["lon"]))
    else:
        aux = get_random_sp_coordinate()
        d_lat, d_lon = (float(aux["lat"]), float(aux["lon"]))

    # 2. Busca Rota (Restaurante -> Cliente)
    waypoints = await fetch_route(client, sem, config, o_lat, o_lon, d_lat, d_lon)

    if not (isinstance(waypoints, list) and len(waypoints) > 0):
        log.debug(f"Rota falhou para pedido {order_id}. Finalizando execução sem simular rota.")
        log.debug(waypoints)
        return
    
    # 3. Transições com Delays Realistas
    async def advance(state: OrderState):
        await _request(client, "PATCH", ORDER_URL, "/order", sem, config, json={"id_order": order_id, "id_state": state.value})
    
    await asyncio.sleep(random.uniform(config.delay_preparing_min, config.delay_preparing_max))
    await advance(OrderState.PREPARING)
    await asyncio.sleep(random.uniform(config.delay_ready_min, config.delay_ready_max))
    await advance(OrderState.READY_FOR_PICKUP)
    await asyncio.sleep(0.1)
    await advance(OrderState.PICKED_UP)
    await asyncio.sleep(0.1)
    await advance(OrderState.IN_TRANSIT)

    # log.info(waypoints)
    # 4. Tracking a cada 100ms (Req. Não-Funcional)
    if courier_id:
        # Limita o tempo da simulação de rota para aproximadamente 5s, mesmo que a rota tenha muitos pontos
        limit_time = int(5.0 / config.position_report_interval)
        if(len(waypoints) > limit_time): 
            step = len(waypoints) // limit_time
            waypoints = waypoints[::step] + [waypoints[-1]]
        
        for wp_lat, wp_lon in waypoints:
            await _request(client, "POST", TRACKING_URL, "/tracking/position", sem, config, json={
                "ID_courier": courier_id, "lat": wp_lat, "lon": wp_lon
            })
            await asyncio.sleep(config.position_report_interval)

    await advance(OrderState.DELIVERED)
    metrics.orders_completed += 1

# ---------------------------------------------------------------------------
# Emissor e Bootstrap
# ---------------------------------------------------------------------------

async def fetch_existing_ids(client: httpx.AsyncClient, sem: asyncio.Semaphore, config: SimConfig):
    users = []
    rests = []
    
    page = 1
    while True:
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
    while True:
        r_body = await _request(client, "GET", CRUD_URL, f"/restaurants?page={page}&itemsPerPage=500", sem, config)    
        if r_body:
            rests.extend([r["id_restaurant"] for r in r_body.get("data", [])])
            if r_body['has_more']:
                page += 1
            else:
                break
        else:
            break                

    return users, rests

async def order_emitter(client, users, restaurants, config):
    sem = asyncio.Semaphore(config.max_concurrent_orders)
    interval = 1.0 / config.orders_per_second
    end_time = time.perf_counter() + config.duration_seconds
    tasks = []

    while time.perf_counter() < end_time:
        t_start = time.perf_counter()
        
        u_id = random.choice(users)
        r_id = random.choice(restaurants)
        tasks.append(asyncio.create_task(run_order_lifecycle(client, sem, u_id, r_id, config)))
        
        # Limpa tasks finalizadas da memória
        tasks = [t for t in tasks if not t.done()]
        
        sleep_for = max(0.0, interval - (time.perf_counter() - t_start))
        await asyncio.sleep(sleep_for)

    if tasks:
        log.info(f"Fim da emissão. Aguardando {len(tasks)} pedidos em andamento...")
        await asyncio.gather(*tasks)

async def main():
    config = SimConfig()
    limits = httpx.Limits(max_connections=config.max_concurrent_orders + 50, max_keepalive_connections=config.max_concurrent_orders)
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        sem_init = asyncio.Semaphore(10)
        users, restaurants = await fetch_existing_ids(client, sem_init, config)

        if not users or not restaurants:
            log.error("Banco vazio! Rode o populate.py antes.")
            return

        log.info(f"Carregados {len(users)} usuários e {len(restaurants)} restaurantes.")
        await order_emitter(client, users, restaurants, config)
        
    metrics.report(config)

if __name__ == "__main__":
    asyncio.run(main())
