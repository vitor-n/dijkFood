from enum import Enum
from pydantic import BaseModel, Field

class CourierStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"

class CourierPositionUpdate(BaseModel):
    ID_courier: int
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    status: CourierStatus = CourierStatus.AVAILABLE

class NearbyCourierRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)

class StatusUpdate(BaseModel):
    ID_courier: int
    status: CourierStatus

class ClaimRequest(BaseModel):
    ID_courier: int
