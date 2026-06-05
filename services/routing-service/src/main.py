import os
import pickle
import functools
import numpy as np
from contextlib import asynccontextmanager

import anyio
import osmnx as ox
import networkx as nx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sklearn.neighbors import BallTree

# Constantes 

GRAPH_PATH = os.getenv("GRAPH_PATH", "/app/data/sao_paulo.pkl")
AVERAGE_SPEED_MS = 40_000 / 3_600   # 40 km/h em m/s
CACHE_SIZE = int(os.getenv("ROUTE_CACHE_SIZE", "2048"))

# Estado do grafo (carregado uma vez por processo) 

G: nx.MultiDiGraph
node_ids: list[int]
spatial_tree: BallTree
node_coords: dict[int, list[float]]   # {node_id: [lat, lon]}


def _load_graph() -> None:
    global G, node_ids, spatial_tree, node_coords

    with open(GRAPH_PATH, "rb") as f:
        G = pickle.load(f)

    # Mantém apenas o maior componente fortemente conectado (SCC).
    scc = max(nx.strongly_connected_components(G), key=len)
    G = G.subgraph(scc).copy()
    print(f"[graph] {G.number_of_nodes()} nós · {G.number_of_edges()} arestas (maior SCC)")

    nodes_gdf = ox.graph_to_gdfs(G, edges=False)
    node_ids = nodes_gdf.index.tolist()

    # BallTree com metrica haversine para snapping rapido de coordenadas.
    coords_rad = np.radians(nodes_gdf[["y", "x"]].values)
    spatial_tree = BallTree(coords_rad, metric="haversine")

    # Dict pre-computado para lookup O(1) por node_id.
    node_coords = {
        nid: row[["y", "x"]].tolist()
        for nid, row in nodes_gdf.iterrows()
    }
    print(f"[graph] índice espacial e dict de coords prontos ({len(node_coords)} nós)")



# Cache de rotas 

@functools.lru_cache(maxsize=CACHE_SIZE)
def _compute_route(orig_node: int, dest_node: int) -> tuple[float, list]:
    """
    Executa Dijkstra bidirecional e retorna (distância_m, lista_de_coords).

    Resultado cacheado por par de nós.
    """
    distance, route_nodes = nx.bidirectional_dijkstra(
        G, orig_node, dest_node, weight="length"
    )

    path = [node_coords[n] for n in route_nodes]
    return round(distance, 2), path


# FastAPI 

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Nota sobre concorrência:
    - O threadpool abaixo permite múltiplas requisições simultâneas no mesmo
      worker, mas as execuções de Dijkstra são serializadas dentro de cada
      processo (GIL não é liberada em código Python puro).
    - Paralelismo real de CPU vem dos --workers do Dockerfile (processos
      separados, cada um com sua própria GIL e cópia do grafo em memória).
    """
    _load_graph()
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = 2
    print(f"[startup] threadpool limitado a {limiter.total_tokens} workers")
    yield


app = FastAPI(title="DijkFood Routing Service", lifespan=lifespan)


# Modelos 

class RouteRequest(BaseModel):
    orig_lat: float
    orig_lon: float
    dest_lat: float
    dest_lon: float


class RouteResponse(BaseModel):
    distance_meters: float
    estimated_time_seconds: float
    path_nodes: list[list[float]]


# Endpoints 

@app.get("/healthz", tags=["ops"])
@app.get("/routes/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.post("/routes/calculate", response_model=RouteResponse)
def find_route(req: RouteRequest):
    # 1. Snap para os nos mais proximos no grafo.
    query_rad = np.radians([
        [req.orig_lat, req.orig_lon],
        [req.dest_lat, req.dest_lon],
    ])
    _, indices = spatial_tree.query(query_rad, k=1)
    orig_node = node_ids[indices[0][0]]
    dest_node = node_ids[indices[1][0]]

    # 2. Dijkstra bidirecional (resultado cacheado por par de nos).
    try:
        distance, path = _compute_route(orig_node, dest_node)
    except nx.NetworkXNoPath:
        raise HTTPException(
            status_code=422,
            detail="Sem rota entre as coordenadas fornecidas.",
        )
    except nx.NodeNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return RouteResponse(
        distance_meters=distance,
        estimated_time_seconds=round(distance / AVERAGE_SPEED_MS, 1),
        path_nodes=path,
    )