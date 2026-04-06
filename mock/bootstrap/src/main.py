"""
DijkFood - Bootstrap
====================
Popula o banco com usuários, restaurantes, itens de menu e entregadores
antes de iniciar o simulador de carga.
"""

import asyncio
import random
import os
import logging
import time
from dataclasses import dataclass, field

import httpx
from faker import Faker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bootstrap")

# ---------------------------------------------------------------------------
# Configuração via env
# ---------------------------------------------------------------------------

BASE_URL            = os.getenv("BASE_URL", "http://localhost:8000")
NUM_USERS           = int(os.getenv("NUM_USERS", 1000))
NUM_RESTAURANTS     = int(os.getenv("NUM_RESTAURANTS", 50))
NUM_COURIERS        = int(os.getenv("NUM_COURIERS", NUM_USERS * 3))
# ITEMS_PER_RESTAURANT = int(os.getenv("ITEMS_PER_RESTAURANT", 8))

# Controle de concorrência — quantas requisições simultâneas por tipo de entidade
CONCURRENCY         = int(os.getenv("BOOTSTRAP_CONCURRENCY", 50))

# Retry
MAX_RETRIES         = int(os.getenv("BOOTSTRAP_MAX_RETRIES", 3))
RETRY_BASE_DELAY    = float(os.getenv("BOOTSTRAP_RETRY_BASE_DELAY", 0.5))  # segundos

fake = Faker("pt_BR")

# Bounding box de São Paulo
SP_LAT_MIN, SP_LAT_MAX = -23.7000, -23.4000
SP_LON_MIN, SP_LON_MAX = -46.8000, -46.3000

CUISINE_TYPE_IDS = list(range(1, 11))
VEHICLE_TYPE_IDS = list(range(1, 5))

# ---------------------------------------------------------------------------
# Resultado agregado
# ---------------------------------------------------------------------------

@dataclass
class BatchResult:
    entity: str
    created: list = field(default_factory=list)   # IDs retornados pela API
    failed: int = 0

    @property
    def total(self):
        return len(self.created) + self.failed

    def log_summary(self):
        log.info(
            f"  {self.entity:<20s} criados={len(self.created):>6d}  "
            f"falhas={self.failed:>6d}  total={self.total:>6d}"
        )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sp_location() -> dict:
    return {
        "lat": round(random.uniform(SP_LAT_MIN, SP_LAT_MAX), 8),
        "lon": round(random.uniform(SP_LON_MIN, SP_LON_MAX), 8),
    }


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    sem: asyncio.Semaphore,
) -> dict | None:
    """
    POST com semáforo de concorrência e retry exponencial.
    Retorna o body JSON em caso de sucesso, None em caso de falha definitiva.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        async with sem:
            try:
                resp = await client.post(url, json=payload)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                log.debug(f"Tentativa {attempt} — erro de rede em {url}: {exc}")
                resp = None

        if resp is not None and resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {}

        # Só faz retry em falhas transitórias
        if resp is not None and resp.status_code < 500:
            log.debug(f"Falha permanente {resp.status_code} em {url}")
            return None

        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.1)
            await asyncio.sleep(delay)

    log.warning(f"Esgotadas {MAX_RETRIES} tentativas para {url}")
    return None

# ---------------------------------------------------------------------------
# Criadores individuais
# ---------------------------------------------------------------------------

async def create_user(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> int | None:
    loc = sp_location()
    body = await post_with_retry(client, f"{BASE_URL}/users", {
        "name":  fake.name(),
        "email": fake.email(),
        "phone": fake.phone_number()[:15],
        "lat":   loc["lat"],
        "lon":   loc["lon"],
    }, sem)
    if body is None:
        return None
    return body.get("id_user") or body.get("id")


async def create_restaurant(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> int | None:
    loc = sp_location()
    body = await post_with_retry(client, f"{BASE_URL}/restaurants", {
        "name":           fake.company(),
        "lat":            loc["lat"],
        "lon":            loc["lon"],
        "H3_index":       random.randint(1, 1000),
        "ID_cuisine_type": random.choice(CUISINE_TYPE_IDS),
    }, sem)
    if body is None:
        return None
    return body.get("id_restaurant") or body.get("id")


# async def create_menu_item(
#     client: httpx.AsyncClient,
#     sem: asyncio.Semaphore,
#     restaurant_id: int,
# ) -> int | None:
#     body = await post_with_retry(client, f"{BASE_URL}/menu_items", {
#         "name":          fake.word().capitalize(),
#         "price":         round(random.uniform(10, 100), 2),
#         "ID_restaurant": restaurant_id,
#     }, sem)
#     return body.get("id") if body is not None else None


async def create_courier(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> int | None:
    # loc = sp_location()
    body = await post_with_retry(client, f"{BASE_URL}/couriers", {
        "name":            fake.name(),
        "ID_vehicle_type": random.choice(VEHICLE_TYPE_IDS),
        # "lat":             loc["lat"],
        # "lon":             loc["lon"],
    }, sem)
    if body is None:
        return None
    return body.get("id_courier") or body.get("id")

# ---------------------------------------------------------------------------
# Ingestão em lote com progresso
# ---------------------------------------------------------------------------

async def ingest_batch(
    label: str,
    coroutines,
    log_every: int = 100,
) -> BatchResult:
    """
    Executa uma lista de corrotinas e agrega os resultados.
    Loga progresso a cada `log_every` itens concluídos.
    """
    result = BatchResult(entity=label)
    total = len(coroutines)
    done = 0
    t0 = time.perf_counter()

    for coro in asyncio.as_completed(coroutines):
        entity_id = await coro
        done += 1
        if entity_id is not None:
            result.created.append(entity_id)
        else:
            result.failed += 1

        if done % log_every == 0 or done == total:
            elapsed = time.perf_counter() - t0
            rps = done / elapsed if elapsed > 0 else 0
            log.info(f"  [{label}] {done}/{total}  ({rps:.1f} req/s)")

    return result

# ---------------------------------------------------------------------------
# Bootstrap principal
# ---------------------------------------------------------------------------

async def run_bootstrap() -> dict:
    """
    Executa o bootstrap completo e retorna os IDs criados:
      {"user_ids": [...], "restaurant_ids": [...], "item_ids": {...}, "courier_ids": [...]}
    """
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    limits  = httpx.Limits(max_connections=CONCURRENCY + 10, max_keepalive_connections=CONCURRENCY)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

        # ── Usuários ────────────────────────────────────────────────────────
        log.info(f"Criando {NUM_USERS} usuários  (concurrency={CONCURRENCY})")
        user_result = await ingest_batch(
            "users",
            [create_user(client, sem) for _ in range(NUM_USERS)],
        )

        # ── Restaurantes ────────────────────────────────────────────────────
        log.info(f"Criando {NUM_RESTAURANTS} restaurantes")
        rest_result = await ingest_batch(
            "restaurants",
            [create_restaurant(client, sem) for _ in range(NUM_RESTAURANTS)],
        )

        # ── Itens de menu ───────────────────────────────────────────────────
        # item_ids: dict[int, list[int]] = {}
        # if rest_result.created:
        #     total_items = len(rest_result.created) * ITEMS_PER_RESTAURANT
        #     log.info(f"Criando {total_items} itens de menu ({ITEMS_PER_RESTAURANT} por restaurante)")
        #     item_coros = [
        #         create_menu_item(client, sem, rid)
        #         for rid in rest_result.created
        #         for _ in range(ITEMS_PER_RESTAURANT)
        #     ]
        #     # Mapeia item → restaurante para retorno estruturado
        #     rid_per_coro = [
        #         rid
        #         for rid in rest_result.created
        #         for _ in range(ITEMS_PER_RESTAURANT)
        #     ]
        #     item_result = await ingest_batch("menu_items", item_coros)

        #     for rid, item_id in zip(rid_per_coro, item_result.created):
        #         item_ids.setdefault(rid, []).append(item_id)
        # else:
        #     log.warning("Nenhum restaurante criado — pulando itens de menu.")
        #     item_result = BatchResult("menu_items")

        # ── Entregadores ────────────────────────────────────────────────────
        log.info(f"Criando {NUM_COURIERS} entregadores")
        courier_result = await ingest_batch(
            "couriers",
            [create_courier(client, sem) for _ in range(NUM_COURIERS)],
        )

    # ── Resumo ───────────────────────────────────────────────────────────────
    log.info("=" * 55)
    log.info("RESUMO DO BOOTSTRAP")
    log.info("=" * 55)
    for r in (user_result, rest_result, courier_result):
        r.log_summary()
    log.info("=" * 55)

    return {
        "user_ids":       user_result.created,
        "restaurant_ids": rest_result.created,
        # "item_ids":       item_ids,          # {restaurant_id: [item_id, ...]}
        "courier_ids":    courier_result.created,
    }


if __name__ == "__main__":
    asyncio.run(run_bootstrap())
