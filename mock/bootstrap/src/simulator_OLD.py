"""
DijkFood - Simulador de Pedidos
================================
Cria pedidos, avança estados e simula tracking de entregadores
usando os 4 serviços já implementados.

Serviços:
  :8000  - CRUD (users, restaurants, couriers)
  :8001  - Orders (create / update)
  :8002  - Tracking (position / status / nearby)
  :8003  - Routes (calculate)

Uso:
  python simulator.py            # cenário padrão (10 req/s)
  SCENARIO=peak python simulator.py   # 50 req/s
  SCENARIO=event python simulator.py  # 200 req/s
"""

import asyncio
import random
import os
import logging
import time
import statistics
from dataclasses import dataclass, field
from enum import Enum

import httpx
from faker import Faker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("simulator")

# ---------------------------------------------------------------------------
# Configuração via env
# ---------------------------------------------------------------------------

CRUD_URL      = os.getenv("CRUD_URL",      "http://localhost:8000")
ORDER_URL     = os.getenv("ORDER_URL",     "http://localhost:8001")
TRACKING_URL  = os.getenv("TRACKING_URL",  "http://localhost:8002")
ROUTE_URL     = os.getenv("ROUTE_URL",     "http://localhost:8003")

# Cenários de carga: normal | peak | event
SCENARIO = os.getenv("SCENARIO", "normal")
SCENARIO_RPS = {"normal": 1, "peak": 50, "event": 200}
TARGET_RPS = SCENARIO_RPS.get(SCENARIO, 1)

# Duração da simulação em segundos
SIM_DURATION = int(os.getenv("SIM_DURATION", 60))

# Concorrência máxima de corrotinas abertas
CONCURRENCY = int(os.getenv("SIM_CONCURRENCY", min(TARGET_RPS * 4, 400)))

# Intervalo entre atualizações de posição do entregador (seg)
POSITION_INTERVAL = float(os.getenv("POSITION_INTERVAL", 0.5))

# Número de passos de posição simulados por pedido
POSITION_STEPS = int(os.getenv("POSITION_STEPS", 5))

# Retry
MAX_RETRIES      = int(os.getenv("SIM_MAX_RETRIES", 1))
RETRY_BASE_DELAY = float(os.getenv("SIM_RETRY_BASE_DELAY", 0.3))

# Bounding box de São Paulo
SP_LAT_MIN, SP_LAT_MAX = -23.7000, -23.4000
SP_LON_MIN, SP_LON_MAX = -46.8000, -46.3000

fake = Faker("pt_BR")

# ---------------------------------------------------------------------------
# Estados do pedido (sequência estrita)
# ---------------------------------------------------------------------------

class OrderState(str, Enum):
    CONFIRMED        = "CONFIRMED"
    PREPARING        = "PREPARING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP        = "PICKED_UP"
    IN_TRANSIT       = "IN_TRANSIT"
    DELIVERED        = "DELIVERED"

ORDER_SEQUENCE = [
    OrderState.CONFIRMED,
    OrderState.PREPARING,
    OrderState.READY_FOR_PICKUP,
    OrderState.PICKED_UP,
    OrderState.IN_TRANSIT,
    OrderState.DELIVERED,
]

# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

@dataclass
class Metrics:
    latencies: list[float] = field(default_factory=list)
    orders_created: int = 0
    orders_completed: int = 0
    orders_failed: int = 0
    state_updates: int = 0
    position_updates: int = 0
    route_calls: int = 0
    errors: int = 0

    def record(self, latency_ms: float):
        self.latencies.append(latency_ms)

    def report(self):
        log.info("=" * 60)
        log.info(f"RELATÓRIO DO SIMULADOR  (cenário={SCENARIO}, {TARGET_RPS} req/s, {SIM_DURATION}s)")
        log.info("=" * 60)
        log.info(f"  Pedidos criados    : {self.orders_created}")
        log.info(f"  Pedidos concluídos : {self.orders_completed}")
        log.info(f"  Pedidos falhos     : {self.orders_failed}")
        log.info(f"  Transições estado  : {self.state_updates}")
        log.info(f"  Updates de posição : {self.position_updates}")
        log.info(f"  Chamadas de rota   : {self.route_calls}")
        log.info(f"  Erros totais       : {self.errors}")
        if self.latencies:
            lat = sorted(self.latencies)
            log.info(f"  Latência (ms):")
            log.info(f"    p50  = {statistics.median(lat):.1f}")
            log.info(f"    p95  = {lat[int(len(lat) * 0.95)]:.1f}")
            log.info(f"    p99  = {lat[int(len(lat) * 0.99)]:.1f}")
            log.info(f"    max  = {lat[-1]:.1f}")
            log.info(f"    mean = {statistics.mean(lat):.1f}")
        log.info("=" * 60)


metrics = Metrics()

# ---------------------------------------------------------------------------
# Helpers HTTP
# ---------------------------------------------------------------------------

def sp_location() -> tuple[float, float]:
    return (
        round(random.uniform(SP_LAT_MIN, SP_LAT_MAX), 8),
        round(random.uniform(SP_LON_MIN, SP_LON_MAX), 8),
    )


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    sem: asyncio.Semaphore,
    **kwargs,
) -> httpx.Response | None:
    """Executa uma requisição com retry e mede latência."""
    for attempt in range(1, MAX_RETRIES + 1):
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.request(method, url, **kwargs)
                elapsed = (time.perf_counter() - t0) * 1000
                metrics.record(elapsed)
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                log.debug(f"Tentativa {attempt} — erro rede {url}: {exc}")
                metrics.errors += 1

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))

    return None


async def post(client, url, sem, payload) -> dict | None:
    resp = await _request(client, "POST", url, sem, json=payload)
    if resp is not None and resp.status_code in (200, 201):
        try:
            return resp.json()
        except Exception:
            return {}
    return None


async def patch(client, url, sem, payload) -> dict | None:
    resp = await _request(client, "PATCH", url, sem, json=payload)
    if resp is not None and resp.status_code in (200, 201):
        try:
            return resp.json()
        except Exception:
            return {}
    return None


async def get(client, url, sem, params=None) -> dict | None:
    resp = await _request(client, "GET", url, sem, params=params)
    if resp is not None and resp.status_code == 200:
        try:
            return resp.json()
        except Exception:
            return {}
    return None

# ---------------------------------------------------------------------------
# Ações do simulador
# ---------------------------------------------------------------------------

async def fetch_route(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    orig_lat: float,
    orig_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> tuple[float, float, list[tuple[float, float]]]:
    """Solicita rota ao serviço :8003 e retorna lista de coordenadas."""
    body = await post(client, f"{ROUTE_URL}/routes/calculate", sem, {
        "orig_lat":  orig_lat,
        "orig_lon":  orig_lon,
        "dest_lat":  dest_lat,
        "dest_lon":  dest_lon,
    })
    metrics.route_calls += 1

    if body:
        distance_meters = body.get("distance_meters", 0)
        estimated_time_seconds = body.get("estimated_time_seconds", 0)
        path_nodes = body.get("path_nodes", [])
        return distance_meters, estimated_time_seconds, path_nodes
    
    # fallback: interpola linearmente entre origem e destino~
    log.debug("Falha ao obter rota, usando interpolação linear")
    steps = POSITION_STEPS
    return [
        (
            orig_lat + (dest_lat - orig_lat) * i / steps,
            orig_lon + (dest_lon - orig_lon) * i / steps,
        )
        for i in range(steps + 1)
    ]


async def update_position(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    courier_id: int,
    lat: float,
    lon: float,
):
    """Envia atualização de posição do entregador ao serviço :8002."""
    await post(client, f"{TRACKING_URL}/tracking/position", sem, {
        "id_courier": courier_id,
        "lat":        lat,
        "lon":        lon,
        "status":    "IN_TRANSIT",
    })
    metrics.position_updates += 1


async def advance_order_state(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    order_id: int,
    new_state: OrderState,
):
    """Avança estado do pedido via PATCH /order (:8001)."""
    await patch(client, f"{ORDER_URL}/order", sem, {
        "id_order": order_id,
        "id_state": new_state.value,
    })
    metrics.state_updates += 1


async def simulate_order(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    user_ids: list[int],
    restaurant_ids: list[int],
):
    """
    Ciclo de vida completo de um pedido:
      1. Cria pedido   → POST /order
      2. Busca rota    → POST /routes/calculate
      3. Avança estados em sequência
      4. Simula updates de posição durante IN_TRANSIT
    """
    if not user_ids or not restaurant_ids:
        metrics.orders_failed += 1
        return

    user_id       = random.choice(user_ids)
    restaurant_id = random.choice(restaurant_ids)

    # ── 1. Criar pedido (POST /order) ───────────────────────────────────────
    body = await post(client, f"{ORDER_URL}/order", sem, {
        "id_user":       user_id,
        "id_restaurant": restaurant_id,
    })

    if not body:
        log.error("Falha ao criar pedido")
        log.error(f"Resposta: {body}")
        metrics.orders_failed += 1
        return

    order_id   = body.get("id_order")
    courier_id = body.get("id_courier")

    if not order_id or not courier_id:
        metrics.orders_failed += 1
        log.debug(f"Resposta incompleta ao criar pedido: {body}")
        return

    metrics.orders_created += 1
    log.debug(f"Pedido {order_id} criado (user={user_id}, rest={restaurant_id}, courier={courier_id})")

    # 2. Buscar coordenadas reais do usuário e do restaurante (:8000)
    user_data = await get(client, f"{CRUD_URL}/users/{user_id}", sem)
    rest_data = await get(client, f"{CRUD_URL}/restaurants/{restaurant_id}", sem)

    if user_data and rest_data:
        origin_lat = float(user_data["lat"])
        origin_lon = float(user_data["lon"])
        dest_lat   = float(rest_data["lat"])
        dest_lon   = float(rest_data["lon"])
    else:
        # fallback para coordenadas aleatórias se o CRUD falhar
        log.debug(f"Não foi possível obter coordenadas reais para pedido {order_id}, usando fallback")
        origin_lat, origin_lon = sp_location()
        dest_lat,   dest_lon   = sp_location()

    _, _, waypoints = await fetch_route(client, sem, origin_lat, origin_lon, dest_lat, dest_lon)

    # 3. Avançar estados em sequência estrita
    for state in ORDER_SEQUENCE:
        await advance_order_state(client, sem, order_id, state)

        # 4. Simular posições durante coleta e trânsito
        if state in (OrderState.PICKED_UP, OrderState.IN_TRANSIT) and courier_id:
            for wp_lat, wp_lon in waypoints:
                await update_position(client, sem, courier_id, order_id, wp_lat, wp_lon)
                await asyncio.sleep(POSITION_INTERVAL)

    metrics.orders_completed += 1
    log.debug(f"Pedido {order_id} concluído")

# ---------------------------------------------------------------------------
# Bootstrap leve: busca IDs existentes do CRUD
# ---------------------------------------------------------------------------

async def fetch_existing_ids(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> dict:
    """Lê usuários e restaurantes do serviço :8000."""
    log.info("Buscando IDs existentes no CRUD...")

    users_body = await get(client, f"{CRUD_URL}/users?itemsPerPage=100", sem)
    rest_body  = await get(client, f"{CRUD_URL}/restaurants?itemsPerPage=100", sem)

    user_ids = []
    restaurant_ids = []

    if isinstance(users_body, dict):
        user_data =  users_body.get("data") or []
        user_ids = [u.get("id_user") for u in user_data if u]

    if isinstance(rest_body, dict):
        rest_data = rest_body.get("data") or []
        restaurant_ids = [r.get("id_restaurant") for r in rest_data if r]

    user_ids       = [i for i in user_ids if i is not None]
    restaurant_ids = [i for i in restaurant_ids if i is not None]

    log.info(f"  Encontrados {len(user_ids)} usuários e {len(restaurant_ids)} restaurantes")
    return {"user_ids": user_ids, "restaurant_ids": restaurant_ids}

# ---------------------------------------------------------------------------
# Loop principal do simulador (rate-limited)
# ---------------------------------------------------------------------------

async def run_simulator(user_ids: list[int], restaurant_ids: list[int]):
    sem     = asyncio.Semaphore(CONCURRENCY)
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    limits  = httpx.Limits(
        max_connections=CONCURRENCY + 20,
        max_keepalive_connections=CONCURRENCY,
    )

    interval = 1.0 / TARGET_RPS   # segundos entre disparos
    end_time = time.perf_counter() + SIM_DURATION
    tasks: list[asyncio.Task] = []

    log.info(f"Iniciando simulação: cenário={SCENARIO}, {TARGET_RPS} req/s, duração={SIM_DURATION}s")

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        while time.perf_counter() < end_time:
            t_start = time.perf_counter()

            task = asyncio.create_task(
                simulate_order(client, sem, user_ids, restaurant_ids)
            )
            tasks.append(task)

            # Remove tarefas concluídas para não vazar memória
            tasks = [t for t in tasks if not t.done()]

            elapsed = time.perf_counter() - t_start
            sleep_for = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_for)

        # Aguarda tarefas pendentes (máx 60s extras)
        if tasks:
            log.info(f"Aguardando {len(tasks)} pedidos em andamento...")
            await asyncio.wait(tasks, timeout=60)

    metrics.report()

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main():
    sem     = asyncio.Semaphore(10)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        ids = await fetch_existing_ids(client, sem)

    if not ids["user_ids"] or not ids["restaurant_ids"]:
        log.error(
            "Nenhum usuário ou restaurante encontrado. "
            "Execute o bootstrap (main.py) antes do simulador."
        )
        return
    log.info("IDs existentes carregados, iniciando simulador...")
    log.info(f"  Usuários: {len(ids['user_ids'])}, Restaurantes: {len(ids['restaurant_ids'])}")
    await run_simulator(ids["user_ids"], ids["restaurant_ids"])


if __name__ == "__main__":
    asyncio.run(main())