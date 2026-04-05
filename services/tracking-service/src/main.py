import time
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel
from functools import lru_cache

import h3
import boto3
from fastapi import FastAPI, Depends, HTTPException, status

from .schemas import CourierPositionUpdate, NearbyCourierRequest
from .config import settings
from .repository import CourierRepository

app = FastAPI(title="DijkFood Tracking Service")

@lru_cache()
def get_courier_repo():
    db = boto3.resource(
        "dynamodb",
        endpoint_url=settings.DYNAMO_ENDPOINT
    )
    table = db.Table("CourierTracking")
    return CourierRepository(table)

@app.post("/tracking/position")
async def update_position(
    data: CourierPositionUpdate,
    repo: CourierRepository = Depends(get_courier_repo)
):
    try:
        repo.update_location(data)
    except e:
        raise HTTPException(status_code=500, detail=str(e))
    return { "message": "position captured" }

@app.get("/tracking/nearby")
async def find_nearby_courier(
    req: NearbyCourierRequest,
    repo: CourierRepository = Depends(get_courier_repo)
):
    return repo.get_nearby(req.lat, req.lon)