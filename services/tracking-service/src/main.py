import time
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel
from functools import lru_cache

import h3
import boto3
from fastapi import FastAPI, Depends, HTTPException, status, Body

from .schemas import CourierStatus, CourierPositionUpdate, NearbyCourierRequest, StatusUpdate
from .config import settings
from .repository import CourierRepository

app = FastAPI(title="DijkFood Tracking Service")

@lru_cache()
def get_courier_repo():
    db = boto3.resource(
        "dynamodb",
        region_name = settings.AWS_REGION
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return { "message": "position captured" }

@app.patch("/tracking/status")
async def update_status(
    req: StatusUpdate,
    repo: CourierRepository = Depends(get_courier_repo)
):
    try:
        repo.update_status(req.ID_courier, req.status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return { "message": "status captured" }

@app.get("/tracking/nearby")
async def find_nearby_courier(
    req: NearbyCourierRequest = Depends(),
    repo: CourierRepository = Depends(get_courier_repo)
):
    return repo.get_nearby(req.lat, req.lon)
