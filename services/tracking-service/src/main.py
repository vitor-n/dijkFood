import time
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel
import time
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel
from functools import lru_cache

from contextlib import asynccontextmanager

import h3
import aioboto3
import botocore.exceptions
from fastapi import FastAPI, Depends, HTTPException, Request, Query

from .schemas import CourierStatus, CourierPositionUpdate, NearbyCourierRequest, StatusUpdate
from .config import settings
from .repository import CourierRepository
from .config import settings
from .dynamo import dynamodb_resource


@asynccontextmanager
async def lifespan(app: FastAPI):
    session = aioboto3.Session()
    
    kwargs = {"region_name": settings.AWS_REGION}
    ep = (settings.DYNAMO_ENDPOINT or "").strip()
    if ep.startswith("http"):
        kwargs["endpoint_url"] = ep
        
    from botocore.config import Config
    boto_config = Config(max_pool_connections=200)
    kwargs["config"] = boto_config

    async with session.resource("dynamodb", **kwargs) as dynamo_resource:
        app.state.dynamodb = dynamo_resource
        app.state.table = await dynamo_resource.Table(settings.DYNAMO_TABLE)
        yield

async def get_courier_repo(request: Request):
    return CourierRepository(request.app.state.table)


app = FastAPI(title="DijkFood Tracking Service", lifespan = lifespan)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.post("/tracking/position")
async def update_position(
    data: CourierPositionUpdate,
    repo: CourierRepository = Depends(get_courier_repo),
):
    try:
        await repo.update_location(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"message": "position captured"}


@app.patch("/tracking/status")
async def update_status(
    req: StatusUpdate,
    repo: CourierRepository = Depends(get_courier_repo),
):
    try:
        await repo.update_status(req.ID_courier, req.status)
    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == "ConditionalCheckFailedException":
            raise HTTPException(
                status_code=409,
                detail="Courier is no longer available"
            )
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"message": "status captured"}


@app.get("/tracking/nearby")
async def find_nearby_courier(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    repo: CourierRepository = Depends(get_courier_repo),
):
    return await repo.get_nearby(lat, lon)
