import os
import pickle
import numpy as np
from pydantic import BaseModel
from sklearn.neighbors import BallTree
from pathlib import Path

import osmnx as ox
import networkx as nx
from fastapi import FastAPI, HTTPException

app = FastAPI(title="DijkFood Routing Service")

@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.get("/routes/healthz", tags=["ops"])
async def routes_healthz():
    return {"status": "ok"}

# DEFAULT_GRAPH_PATH = Path(__file__).resolve().parent.parent / "data" / "sao_paulo.pkl"
GRAPH_PATH = "/app/data/sao_paulo.pkl"

with open(GRAPH_PATH, "rb") as f:
    G = pickle.load(f)

class RouteRequest(BaseModel):
    orig_lat: float
    orig_lon: float
    
    dest_lat: float
    dest_lon: float

class RouteResponse(BaseModel):
    distance_meters: float
    estimated_time_seconds: float
    path_nodes: list[list[float, float]]

nodes_data = ox.graph_to_gdfs(G, edges=False)
node_ids = nodes_data.index.tolist()
coords_radians = np.radians(nodes_data[["y", "x"]].values)
spatial_tree = BallTree(coords_radians, metric="haversine")

@app.post("/routes/calculate", response_model=RouteResponse)
async def find_route(req: RouteRequest):
    query_coords = np.radians([
        [req.orig_lat, req.orig_lon],
        [req.dest_lat, req.dest_lon]
    ])
    
    # finds the closest map nodes to the origin and destiny positions
    _, indices = spatial_tree.query(query_coords, k=1)
    orig_node = node_ids[indices[0][0]]
    dest_node = node_ids[indices[1][0]]
    
    distance, route = nx.bidirectional_dijkstra(G, orig_node, dest_node, weight="length")
    route = list(map(lambda x: nodes_data.loc[x][["y", "x"]].values.tolist(), route))

    return RouteResponse(
            distance_meters = round(distance, 2),
            estimated_time_seconds = -1,
            path_nodes = route
        )
