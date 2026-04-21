import asyncio
import json, os
import random
import requests
import httpx
import logging
from shapely.geometry import Polygon, Point

URL_POLYGON_SP = "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/3550308?formato=application/json&qualidade=minima"
FILE_NAME_POLYGON_SP = "polygon_sp.json"

async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    sem: asyncio.Semaphore,
    config: dict,
    log: logging.Logger,
):
    """
    POST com semáforo de concorrência e retry exponencial.
    Retorna o body JSON em caso de sucesso, None em caso de falha definitiva.
    """
    for attempt in range(1, config['MAX_RETRIES'] + 1):
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

        if attempt < config['MAX_RETRIES']:
            delay = config['RETRY_BASE_DELAY'] * (2 ** (attempt - 1)) + random.uniform(0, 0.1)
            await asyncio.sleep(delay)

    log.warning(f"Esgotadas {config['MAX_RETRIES']} tentativas para {url}")
    return None

def get_polygon_sp():
    # Carrega arquivo local se existir
    if os.path.exists(FILE_NAME_POLYGON_SP):
        with open(FILE_NAME_POLYGON_SP, "r") as f:
            coords = json.load(f)
        return Polygon(coords)

    # Caso contrário, busca na API do IBGE
    data = requests.get(URL_POLYGON_SP).json()
    
    scale = data["transform"]["scale"]
    translate = data["transform"]["translate"]
    
    coords = []
    x, y = 0, 0
    for dx, dy in data["arcs"][0]:
        x += dx
        y += dy
        lon = x * scale[0] + translate[0]
        lat = y * scale[1] + translate[1]
        coords.append((lon, lat))
        
    # Salva para uso futuro
    with open(FILE_NAME_POLYGON_SP, "w") as f:
        json.dump(coords, f)
        
    return Polygon(coords)

def get_random_sp_coordinate():
    """
    Gera coordenada aleatória dentro do polígono de São Paulo
    """
    min_x, min_y, max_x, max_y = polygon_sp.bounds
    
    while True:
        ponto = Point(random.uniform(min_x, max_x), random.uniform(min_y, max_y))
        
        if polygon_sp.contains(ponto):
            return {"lat": ponto.y, "lon": ponto.x}

polygon_sp = get_polygon_sp()

if __name__ == "__main__":
    coord = get_random_sp_coordinate()
    print(f"Latitude: {coord['lat']}, Longitude: {coord['lon']}")