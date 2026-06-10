import os
import httpx
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel


OSRM_URL = os.getenv("OSRM_URL", "http://localhost:5000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=500)
    app.state.client = httpx.AsyncClient(
        base_url=OSRM_URL,
        timeout=10.0,
        limits=limits,
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="DijkFood Routing Service", lifespan=lifespan)


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.client


# ── Modelos ──────────────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    orig_lat: float
    orig_lon: float
    dest_lat: float
    dest_lon: float


class RouteResponse(BaseModel):
    distance_meters: float
    estimated_time_seconds: float
    path_nodes: list[list[float]]


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/healthz", tags=["ops"])
@app.get("/routes/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.post("/routes/calculate", response_model=RouteResponse)
async def find_route(
    req: RouteRequest,
    client: httpx.AsyncClient = Depends(get_client),
):
    # OSRM espera coordenadas no formato lon,lat (longitude primeiro)
    coords = f"{req.orig_lon},{req.orig_lat};{req.dest_lon},{req.dest_lat}"

    try:
        r = await client.get(
            f"/route/v1/driving/{coords}",
            params={"overview": "full", "geometries": "geojson"},
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"OSRM backend indisponível: {exc}") from exc

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OSRM retornou erro {r.status_code}: {r.text}")

    data = r.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise HTTPException(
            status_code=422,
            detail=f"Sem rota entre as coordenadas fornecidas. (OSRM code: {data.get('code')})",
        )

    route = data["routes"][0]

    # GeoJSON retorna [lon, lat]; convertemos para [lat, lon] para manter
    # compatibilidade com o contrato anterior da API
    path_nodes = [[p[1], p[0]] for p in route["geometry"]["coordinates"]]

    return RouteResponse(
        distance_meters=route["distance"],
        estimated_time_seconds=route["duration"],
        path_nodes=path_nodes,
    )