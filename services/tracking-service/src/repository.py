import h3
import time
from decimal import Decimal

from typing import List, Dict
from .utils import generate_cell_index
from .schemas import CourierPositionUpdate

class CourierRepository:
    def __init__(self, table):
        self.table = table

    def update_location(self, data: CourierPositionUpdate):
        cell_index = generate_cell_index(data.lat, data.lon)

        self.table.put_item(
            Item={
                "ID_courier": data.ID_courier,
                "cell_index": cell_index,
                "lat":        Decimal(str(data.lat)),
                "lon":        Decimal(str(data.lon)),
                "status":     data.status.value,
                "updated_at": int(time.time()*1000)
            }
        )

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
                ":avail": "AVAILABLE"
            }
        )

        print(response)