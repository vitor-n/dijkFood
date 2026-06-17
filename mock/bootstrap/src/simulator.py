"""
DijkFood - Simulador de Carga e Ciclo de Vida
=================================================

Uso:
  python simulator.py                 # cenário padrão (10 req/s)
  SCENARIO=peak python simulator.py   # 50 req/s
  SCENARIO=event python simulator.py  # 200 req/s
  SCENARIO=anomaly python simulator.py # injeta entregas lentas p/ a camada preditiva
  PLOT_METRICS=1 python simulator.py  # Plota métricas de latência

  BASE_URL=url SCENARIO=testing SIM_DURATION=10 PLOT_METRICS=1 python simulator.py 
"""

import asyncio
import random
import time
import httpx
import logging
from datetime import datetime

from config import SimConfig, CRUD_URL, TRACKING_URL, BASE_URL
from metrics import metrics
from lifecycle import run_order_lifecycle, _request

log = logging.getLogger("simulator")

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
            if u_body.get('has_more', False):
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
            if r_body.get('has_more', False):
                page += 1
            else:
                break
        else:
            break

    page = 1
    items_by_rest = {}
    while page <= MAX_PAGES:
        i_body = await _request(client, "GET", CRUD_URL, f"/items?page={page}&itemsPerPage=500", sem, config)
        if i_body:
            for i in i_body.get("data", []):
                r_id = i["id_restaurant"]
                if r_id not in items_by_rest:
                    items_by_rest[r_id] = []
                items_by_rest[r_id].append({"id_item": i["id_item"]})
            if i_body.get('has_more', False):
                page += 1
            else:
                break
        else:
            break

    return users, rests, rests_meta, items_by_rest


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


def build_anomaly_targets(rests_meta: list, config: SimConfig):
    """Escolhe a região 'afligida' (entregas lentas) e o conjunto de restaurantes
    nela. Retorna (anomaly_region, slow_restaurant_ids). Se a injeção estiver
    desligada, retorna (None, set())."""
    if config.slow_delivery_pct <= 0.0 or not rests_meta:
        return None, set()

    # Região alvo: explícita (ANOMALY_REGION) ou a que tem mais restaurantes
    # (maximiza o volume e, com isso, a robustez estatística da detecção).
    if config.anomaly_region:
        region = config.anomaly_region
    else:
        by_region: dict = {}
        for m in rests_meta:
            h3 = m.get("h3")
            if h3 is not None:
                by_region.setdefault(str(h3), []).append(m["id"])
        if not by_region:
            log.warning("[cenário] sem regiões (h3) para injetar anomalia")
            return None, set()
        region = max(by_region, key=lambda r: len(by_region[r]))

    slow_ids = {m["id"] for m in rests_meta if str(m.get("h3")) == str(region)}
    log.info(f"[cenário] anomalia: região {region} com {len(slow_ids)} restaurantes — "
             f"{config.slow_delivery_pct:.0%} dos pedidos com atraso de "
             f"{config.slow_delivery_min_s:.0f}-{config.slow_delivery_max_s:.0f}s")
    return region, slow_ids


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
            if body.get("has_more", False):
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

async def order_emitter(client, users, restaurants, config, weights=None, items_by_rest=None, slow_restaurant_ids=None):
    sem = asyncio.Semaphore(config.max_concurrent_orders)
    interval = 1.0 / config.orders_per_second
    end_time = time.perf_counter() + config.duration_seconds
    tasks = set()

    def _on_order_done(task: asyncio.Task):
        tasks.discard(task)
        metrics.max_simultaneous_orders = max(metrics.max_simultaneous_orders, len(tasks))
        try:
            task.result()
        except Exception as e:
            if not config.silent:
                log.error(f"Erro não tratado na lifecycle do pedido: {e}")
        print(f"Pedidos em andamento restantes: {len(tasks)}")
        log.info(f"Pedidos em andamento restantes: {len(tasks)}")

    while time.perf_counter() < end_time:
        t_start = time.perf_counter()

        u_id = random.choice(users)
        # Amostragem ponderada quando há cenário de hotspot/concentração.
        if weights is not None:
            r_id = random.choices(restaurants, weights=weights, k=1)[0]
        else:
            r_id = random.choice(restaurants)

        # Injeta atraso (entrega lenta) numa fração dos pedidos da região afligida.
        inject_delay_s = 0.0
        if slow_restaurant_ids and r_id in slow_restaurant_ids and random.random() < config.slow_delivery_pct:
            inject_delay_s = random.uniform(config.slow_delivery_min_s, config.slow_delivery_max_s)

        task = asyncio.create_task(run_order_lifecycle(
            client, sem, u_id, r_id, config,
            items_menu=items_by_rest.get(r_id, []) if items_by_rest else [],
            inject_delay_s=inject_delay_s,
        ))
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
        users, restaurants, rests_meta, items_by_rest = await fetch_existing_ids(client, sem_init, config)

        if not users or not restaurants:
            log.error("Banco vazio! Rode o populate.py antes.")
            return

        log.info(f"Carregados {len(users)} usuários e {len(restaurants)} restaurantes.")

        # Anomalia (A2): escolhe a região afligida e concentra a demanda nela
        # (via mecanismo de hotspot) para garantir volume suficiente à detecção.
        anomaly_region, slow_restaurant_ids = build_anomaly_targets(rests_meta, config)
        if anomaly_region and not config.hotspot_region:
            config.hotspot_region = anomaly_region
            if config.hotspot_weight == 0.0:
                config.hotspot_weight = 0.5

        # Cenários operacionais (A2): população ponderada + outage de entregadores.
        population, weights = build_restaurant_population(rests_meta, config)
        await apply_courier_outage(client, sem_init, config)

        await order_emitter(client, users, population or restaurants, config,
                            weights=weights, items_by_rest=items_by_rest,
                            slow_restaurant_ids=slow_restaurant_ids)

    total_duration = time.perf_counter() - sim_start
    metrics.report(config, total_duration)

if __name__ == "__main__":
    print(BASE_URL)
    asyncio.run(main())
