import time
from decimal import Decimal
from typing import List, Dict, Any

import h3
import botocore

from .utils import generate_cell_index
from .schemas import CourierStatus, CourierPositionUpdate


def _jsonify_item(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            out[k] = int(v) if k == "ID_courier" else float(v)
        else:
            out[k] = v
    return out


class CourierRepository:
    def __init__(self, table):
        self.table = table

    def update_status(self, ID_courier: int, status: CourierStatus):
        self.table.update_item(
            Key={
                "ID_courier": ID_courier,
            },
            UpdateExpression="SET #s = :new_status, updated_at = :now",
            ExpressionAttributeNames={
                "#s": "status"
            },
            ExpressionAttributeValues={
                ":new_status": status,
                ":now": int(time.time()*1000)
            },
            ConditionExpression="attribute_exists(ID_courier)"
        )

    def update_location(self, data: CourierPositionUpdate):
        cell_index = generate_cell_index(data.lat, data.lon)

        self.table.update_item(
            Key={"ID_courier": data.ID_courier},
            UpdateExpression="SET cell_index = :c, lat = :la, lon = :lo, #s = :st, updated_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":c": cell_index,
                ":la": Decimal(str(data.lat)),
                ":lo": Decimal(str(data.lon)),
                ":st": data.status.value,
                ":u": int(time.time() * 1000),
            },
            ConditionExpression="attribute_exists(ID_courier)",
        )

    def get_nearby(self, lat: float, lon: float) -> dict[str, Any]:
        center_cell = generate_cell_index(lat, lon)
        cells_to_search = h3.grid_disk(center_cell, 1)

        couriers = []

        response = self.table.query(
            IndexName="CellIndex",
            KeyConditionExpression="cell_index = :ci",
            FilterExpression="#s = :avail",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":ci": center_cell,
                ":avail": CourierStatus.AVAILABLE
            }
        )

        return response
