import os
import pickle
from pydantic import BaseModel
from pydantic_extra_types.coordinate import Coordinate

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

@app.post("/get_route", response_model=RouteResponse)
async def get_route(req: RouteRequest):
    orig_node = ox.distance.nearest_nodes(G, req.store_lon, req.store_lat)
    dest_node = ox.distance.nearest_nodes(G, req.client_lon, req.client_lat)
    
    distance, route = nx.bidirectional_dijkstra(G, orig_node, dest_node, weight="length")

    return RouteResponse(
            distance_meters = round(distance, 2),
            estimated_time_seconds = -1,
            path_nodes = route
        )