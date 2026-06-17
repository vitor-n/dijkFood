import asyncio
import random
import time
import httpx
import logging

from config import SimConfig, OrderState, CRUD_URL, ORDER_URL, TRACKING_URL, ROUTE_URL
from metrics import metrics

log = logging.getLogger("simulator")

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
                
                import re
                from urllib.parse import urlparse
                # Remove query strings e agrupa IDs numéricos (ex: /items?page=1 -> /items, /users/123 -> /users/{id})
                base_path = urlparse(path).path
                metric_path = re.sub(r'/\d+', '/{id}', base_path)
                
                # Registra latência apenas de requisições concluídas
                metrics.record_latency(metric_path, method, latency, resp.status_code)
                
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

async def run_order_lifecycle(client: httpx.AsyncClient, sem: asyncio.Semaphore, user_id: int, restaurant_id: int, config: SimConfig, items_menu: list = None, inject_delay_s: float = 0.0):
    # 1. Criação
    payload = {"id_user": user_id, "id_restaurant": restaurant_id}
    if items_menu:
        num_items = random.randint(1, min(5, len(items_menu)))
        chosen = random.choices(items_menu, k=num_items)
        payload["items"] = [
            {"id_item": item["id_item"], "price": round(random.uniform(10, 100), 2)}
            for item in chosen
        ]

    body = await _request(client, "POST", ORDER_URL, "/order", sem, config, json=payload)
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
    
    if rest_data and rest_data.get("lat") is not None and rest_data.get("lon") is not None:
        o_lat, o_lon = (float(rest_data["lat"]), float(rest_data["lon"]))
    else:
        metrics.orders_failed += 1
        log.warning(f"Coordenadas do restaurante {restaurant_id} não encontradas para pedido {order_id}. Finalizando execução sem simular rota.")
        return
    if user_data and user_data.get("lat") is not None and user_data.get("lon") is not None:
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

    # 5. Anomalia injetada: atraso extra antes da entrega (entrega lenta).
    #    Vira outlier de ETA (detecção via MAD na camada preditiva).
    if inject_delay_s > 0:
        await asyncio.sleep(inject_delay_s)

    # 6. Estado Final (IN_TRANSIT -> DELIVERED)
    result = await advance(OrderState.DELIVERED)
    if not result:
        metrics.orders_failed += 1
        log.warning(f"Falha ao avançar para DELIVERED no pedido {order_id}.")
        return
    metrics.orders_completed += 1
