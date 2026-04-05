"""
DijkFood - Simulador de Ciclo de Vida de Pedidos
=================================================
Cria pedidos em taxa configurável e simula cada etapa do ciclo de vida:
  CONFIRMED → PREPARING → READY_FOR_PICKUP → PICKED_UP → IN_TRANSIT → DELIVERED

Além disso, simula o entregador reportando posição a cada 100ms enquanto em rota,
e coleta métricas de latência de cada chamada à API.
"""

import asyncio
import random
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import aiohttp

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000"  # Troque pelo endpoint real

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("simulator")


@dataclass
class SimConfig:
    orders_per_second: float = 10.0          # Taxa de emissão de pedidos
    position_report_interval: float = 0.1   # 100ms entre reports de posição
    # Delays simulados para cada estado (segundos) — valores aleátorios entre min e max
    delay_preparing_min: float = 5.0
    delay_preparing_max: float = 15.0
    delay_ready_min: float = 5.0
    delay_ready_max: float = 10.0
    max_concurrent_orders: int = 200         # Limite de pedidos simultâneos
    total_orders: Optional[int] = None       # None = roda indefinidamente


# ---------------------------------------------------------------------------
# Coleta de métricas
# ---------------------------------------------------------------------------

@dataclass
class LatencyMetrics:
    records: list = field(default_factory=list)

    def record(self, endpoint: str, method: str, latency_ms: float, status: int):
        self.records.append({
            "endpoint": endpoint,
            "method": method,
            "latency_ms": latency_ms,
            "status": status,
            "ts": time.time(),
        })

    def report(self):
        if not self.records:
            log.info("Nenhuma métrica coletada.")
            return
        by_endpoint: dict = {}
        for r in self.records:
            key = f"{r['method']} {r['endpoint']}"
            by_endpoint.setdefault(key, []).append(r["latency_ms"])

        log.info("=" * 60)
        log.info("RELATÓRIO DE LATÊNCIA")
        log.info("=" * 60)
        for key, latencies in sorted(by_endpoint.items()):
            latencies.sort()
            n = len(latencies)
            p50 = latencies[n // 2]
            p95 = latencies[int(n * 0.95)]
            p99 = latencies[int(n * 0.99)]
            avg = sum(latencies) / n
            log.info(
                f"{key:45s} n={n:5d}  avg={avg:7.1f}ms  p50={p50:7.1f}ms"
                f"  p95={p95:7.1f}ms  p99={p99:7.1f}ms"
            )
        log.info("=" * 60)


metrics = LatencyMetrics()


# ---------------------------------------------------------------------------
# Helpers HTTP
# ---------------------------------------------------------------------------

async def api_call(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    **kwargs,
) -> tuple[int, dict]:
    """Faz uma chamada à API e registra a latência. Retorna (status, body)."""
    url = f"{BASE_URL}{path}"
    t0 = time.perf_counter()
    try:
        async with session.request(method, url, **kwargs) as resp:
            latency = (time.perf_counter() - t0) * 1000
            metrics.record(path, method, latency, resp.status)
            try:
                body = await resp.json()
            except Exception:
                body = {}
            return resp.status, body
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000
        metrics.record(path, method, latency, 0)
        log.warning(f"Erro em {method} {path}: {exc}")
        return 0, {}


# ---------------------------------------------------------------------------
# Simulação de posição do entregador
# ---------------------------------------------------------------------------

async def simulate_courier_position(
    session: aiohttp.ClientSession,
    courier_id: int,
    route: list[dict],
    stop_event: asyncio.Event,
    config: SimConfig,
):
    """
    Percorre os waypoints da rota reportando posição a cada 100ms.
    Para quando stop_event é setado ou a rota acaba.
    """
    if not route:
        return

    interval = config.position_report_interval
    for waypoint in route:
        if stop_event.is_set():
            break
        payload = {
            "courier_id": courier_id,
            "lat": waypoint.get("lat", 0),
            "lon": waypoint.get("lon", 0),
        }
        await api_call(session, "PATCH", "/courier_status", json=payload)
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Ciclo de vida de um pedido
# ---------------------------------------------------------------------------

async def run_order_lifecycle(
    session: aiohttp.ClientSession,
    user_id: int,
    restaurant_id: int,
    items: list[int],
    config: SimConfig,
):
    """Executa o ciclo de vida completo de um pedido."""

    # ── 1. Criar pedido (POST /order) ───────────────────────────────────────
    status, body = await api_call(
        session,
        "POST",
        "/order",
        json={"user_id": user_id, "restaurant_id": restaurant_id, "items": items},
    )
    if status not in (200, 201) or "id" not in body:
        log.warning(f"Falha ao criar pedido para user={user_id}: status={status}")
        return

    order_id = body["id"]
    courier_id = body.get("courier_id")
    log.info(f"[order={order_id}] Criado — courier={courier_id}")

    # ── 2. Delay até restaurante começar a preparar ──────────────────────────
    await asyncio.sleep(
        random.uniform(config.delay_preparing_min, config.delay_preparing_max)
    )

    # ── 3. CONFIRMED → PREPARING (PATCH /order) ──────────────────────────────
    status, body = await api_call(
        session, "PATCH", f"/order/{order_id}", json={"order_id": order_id}
    )
    if status not in (200, 201):
        log.warning(f"[order={order_id}] Falha na transição CONFIRMED→PREPARING")
        return
    route_to_restaurant = body.get("route", [])
    log.info(f"[order={order_id}] PREPARING — rota para restaurante recebida")

    # Entregador se desloca para o restaurante enquanto prato é preparado
    courier_arrived_at_restaurant = asyncio.Event()
    courier_stop = asyncio.Event()

    async def courier_travel_to_restaurant():
        await simulate_courier_position(
            session, courier_id, route_to_restaurant, courier_stop, config
        )
        courier_arrived_at_restaurant.set()

    travel_task = asyncio.create_task(courier_travel_to_restaurant())

    # ── 4. Delay PREPARING → READY FOR PICKUP ────────────────────────────────
    await asyncio.sleep(
        random.uniform(config.delay_ready_min, config.delay_ready_max)
    )

    # ── 5. PREPARING → READY FOR PICKUP ──────────────────────────────────────
    status, _ = await api_call(
        session, "PATCH", f"/order/{order_id}", json={"order_id": order_id}
    )
    if status not in (200, 201):
        log.warning(f"[order={order_id}] Falha na transição PREPARING→READY_FOR_PICKUP")
        courier_stop.set()
        await travel_task
        return
    log.info(f"[order={order_id}] READY_FOR_PICKUP")

    # Aguarda entregador chegar ao restaurante antes de continuar
    await courier_arrived_at_restaurant.wait()
    courier_stop.set()
    await travel_task

    # ── 6. READY FOR PICKUP → PICKED UP ──────────────────────────────────────
    status, _ = await api_call(
        session, "PATCH", f"/order/{order_id}", json={"order_id": order_id}
    )
    if status not in (200, 201):
        log.warning(f"[order={order_id}] Falha na transição READY_FOR_PICKUP→PICKED_UP")
        return
    log.info(f"[order={order_id}] PICKED_UP")

    # ── 7. PICKED UP → IN TRANSIT ────────────────────────────────────────────
    status, body = await api_call(
        session, "PATCH", f"/order/{order_id}", json={"order_id": order_id}
    )
    if status not in (200, 201):
        log.warning(f"[order={order_id}] Falha na transição PICKED_UP→IN_TRANSIT")
        return
    route_to_client = body.get("route", [])
    log.info(f"[order={order_id}] IN_TRANSIT — rota para cliente recebida")

    # Entregador percorre rota até o cliente
    courier_arrived_at_client = asyncio.Event()
    courier_stop2 = asyncio.Event()

    async def courier_travel_to_client():
        await simulate_courier_position(
            session, courier_id, route_to_client, courier_stop2, config
        )
        courier_arrived_at_client.set()

    travel_task2 = asyncio.create_task(courier_travel_to_client())
    await courier_arrived_at_client.wait()
    courier_stop2.set()
    await travel_task2

    # ── 8. IN TRANSIT → DELIVERED ────────────────────────────────────────────
    status, _ = await api_call(
        session, "PATCH", f"/order/{order_id}", json={"order_id": order_id}
    )
    if status not in (200, 201):
        log.warning(f"[order={order_id}] Falha na transição IN_TRANSIT→DELIVERED")
        return
    log.info(f"[order={order_id}] DELIVERED ✓")


# ---------------------------------------------------------------------------
# Emissor de pedidos — controla a taxa (pedidos/segundo)
# ---------------------------------------------------------------------------

async def order_emitter(
    session: aiohttp.ClientSession,
    users: list[int],
    restaurants: list[tuple[int, list[int]]],  # [(restaurant_id, [item_ids])]
    config: SimConfig,
    semaphore: asyncio.Semaphore,
):
    """Emite pedidos na taxa configurada, respeitando o semáforo de concorrência."""
    interval = 1.0 / config.orders_per_second
    count = 0

    while config.total_orders is None or count < config.total_orders:
        user_id = random.choice(users)
        restaurant_id, items = random.choice(restaurants)
        chosen_items = random.sample(items, k=min(3, len(items)))

        async def lifecycle(u=user_id, r=restaurant_id, it=chosen_items):
            async with semaphore:
                await run_order_lifecycle(session, u, r, it, config)

        asyncio.create_task(lifecycle())
        count += 1
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Carregamento de dados do bootstrap
# ---------------------------------------------------------------------------

async def load_bootstrap_data(session: aiohttp.ClientSession) -> tuple[list, list]:
    """
    Carrega usuários e restaurantes (com items) cadastrados via bootstrap.
    Adapte conforme sua implementação de bootstrap.
    """
    # Busca lista de usuários
    _, users_body = await api_call(session, "GET", "/admin/user")
    user_ids = [u["id"] for u in users_body.get("users", [])]

    # Busca lista de restaurantes
    _, stores_body = await api_call(session, "GET", "/admin/store")
    restaurants = []
    for store in stores_body.get("stores", []):
        rid = store["id"]
        _, items_body = await api_call(session, "GET", f"/store/{rid}")
        item_ids = [i["id"] for i in items_body.get("items", [])]
        if item_ids:
            restaurants.append((rid, item_ids))

    return user_ids, restaurants


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main(config: SimConfig):
    connector = aiohttp.TCPConnector(limit=500)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        log.info("Carregando dados do bootstrap...")
        users, restaurants = await load_bootstrap_data(session)

        if not users or not restaurants:
            log.error("Nenhum usuário ou restaurante encontrado. Execute o bootstrap primeiro.")
            return

        log.info(
            f"Iniciando simulação: {config.orders_per_second} pedidos/s | "
            f"{len(users)} usuários | {len(restaurants)} restaurantes"
        )

        semaphore = asyncio.Semaphore(config.max_concurrent_orders)

        try:
            await order_emitter(session, users, restaurants, config, semaphore)
        except asyncio.CancelledError:
            log.info("Simulação interrompida pelo usuário.")
        finally:
            # Aguarda tarefas em andamento terminarem (até 60s)
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if pending:
                log.info(f"Aguardando {len(pending)} pedidos em andamento...")
                await asyncio.wait(pending, timeout=60)
            metrics.report()


# ---------------------------------------------------------------------------
# Entrypoint — lê configuração de variáveis de ambiente
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_optional_int(name: str) -> Optional[int]:
    val = os.environ.get(name, "").strip()
    if val == "" or val.lower() == "none":
        return None
    try:
        return int(val)
    except ValueError:
        return None


if __name__ == "__main__":
    import os

    BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

    cfg = SimConfig(
        orders_per_second      = _env_float("ORDERS_PER_SECOND", 10.0),
        total_orders           = _env_optional_int("TOTAL_ORDERS"),
        max_concurrent_orders  = _env_int("MAX_CONCURRENT_ORDERS", 200),
        position_report_interval = _env_float("POSITION_REPORT_INTERVAL", 0.1),
        delay_preparing_min    = _env_float("DELAY_PREPARING_MIN", 5.0),
        delay_preparing_max    = _env_float("DELAY_PREPARING_MAX", 15.0),
        delay_ready_min        = _env_float("DELAY_READY_MIN", 5.0),
        delay_ready_max        = _env_float("DELAY_READY_MAX", 10.0),
    )

    log.info(
        f"Config: url={BASE_URL} rate={cfg.orders_per_second}/s "
        f"total={cfg.total_orders} concurrency={cfg.max_concurrent_orders}"
    )

    asyncio.run(main(cfg))