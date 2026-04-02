import os
import pickle
import numpy as np
from pydantic import BaseModel
from sklearn.neighbors import BallTree

import osmnx as ox
import networkx as nx
from fastapi import FastAPI, HTTPException

app = FastAPI(title="DjiFood Routing Service")

GRAPH_PATH = os.getenv("GRAPH_PATH", "data/sao_paulo.pkl")

with open(GRAPH_PATH, "rb") as f:
    G = pickle.load(f)

class RouteRequest(BaseModel):
    store_lat: float
    store_lon: float
    
    client_lat: float
    client_lon: float

    # courier_lat: float
    # courier_lon: float

class RouteResponse(BaseModel):
    distance_meters: float
    estimated_time_seconds: float
    path_nodes: list[int]

nodes_data = ox.graph_to_gdfs(G, edges=False)
node_ids = nodes_data.index.tolist()
coords_radians = np.radians(nodes_data[["y", "x"]].values)
spatial_tree = BallTree(coords_radians, metric="haversine")

@app.post("/routes/calculate", response_model=RouteResponse)
async def find_route(req: RouteRequest):
    query_coords = np.radians([
        [req.store_lat, req.store_lon],
        [req.client_lat, req.client_lon]
    ])
    
    # finds the closest nodes to the store and client positions
    _, indices = spatial_tree.query(query_coords, k=1)
    orig_node = node_ids[indices[0][0]]
    dest_node = node_ids[indices[1][0]]
    
    distance, route = nx.bidirectional_dijkstra(G, orig_node, dest_node, weight="length")

    return RouteResponse(
            distance_meters = round(distance, 2),
            estimated_time_seconds = -1,
            path_nodes = route
        )
