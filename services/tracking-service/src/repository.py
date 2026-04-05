import time
from decimal import Decimal
from typing import List, Dict

import h3
import botocore

from .utils import generate_cell_index
from .schemas import CourierStatus, CourierPositionUpdate

class CourierRepository:
    def __init__(self, table):
        self.table = table

    def update_location(self, data: CourierPositionUpdate):
        cell_index = generate_cell_index(data.lat, data.lon)

        try:
            self.table.put_item(
                Item={
                    "ID_courier": data.ID_courier,
                    "cell_index": cell_index,
                    "lat":        Decimal(str(data.lat)),
                    "lon":        Decimal(str(data.lon)),
                    "status":     data.status.value,
                    "updated_at": int(time.time()*1000)
                },
                ConditionExpression="attribute_exists(ID_courier)"
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"Courier {data.ID_courier} does not exist.")
            else:
                raise e

    def get_nearby(self, lat: float, lon: float) -> List[Dict]:
        center_cell = generate_cell_index(lat, lon)
        cells_to_search = h3.grid_disk(center_cell, 1)

        couriers = []

        response = self.table.query(
            IndexName="CellIndexIndex",
            KeyConditionExpression="cell_index = :ci",
            FilterExpression="#s = :avail",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":ci": center_cell,
                ":avail": CourierStatus.AVAILABLE
            }
        )

        return response