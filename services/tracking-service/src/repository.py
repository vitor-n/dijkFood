import asyncio
import time
from decimal import Decimal
from typing import List, Dict, Any

import h3

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

    async def update_status(self, ID_courier: int, status: CourierStatus):
        cond = "attribute_exists(ID_courier)"
        expr_vals = {
            ":new_status": status.value if hasattr(status, "value") else status,
            ":now": int(time.time() * 1000)
        }
        
        # Se estiver mudando para BUSY, exige que o entregador esteja AVAILABLE atualmente
        if status == CourierStatus.BUSY or status == "BUSY":
            cond += " AND #s = :expected_old_status"
            expr_vals[":expected_old_status"] = CourierStatus.AVAILABLE.value

        await self.table.update_item(
            Key={
                "ID_courier": ID_courier,
            },
            UpdateExpression="SET #s = :new_status, updated_at = :now",
            ExpressionAttributeNames={
                "#s": "status"
            },
            ExpressionAttributeValues=expr_vals,
            ConditionExpression=cond
        )

    async def update_location(self, data: CourierPositionUpdate):
        cell_index = generate_cell_index(data.lat, data.lon)

        # Atualiza a localização no DynamoDB.
        # IMPORTANTE: Não atualizamos o status aqui para evitar que atualizações de posição
        # enviadas por entregadores em trânsito (BUSY) sobrescrevam seu status para AVAILABLE.
        await self.table.update_item(
            Key={"ID_courier": data.ID_courier},
            UpdateExpression="SET cell_index = :c, lat = :la, lon = :lo, updated_at = :u",
            ExpressionAttributeValues={
                ":c": cell_index,
                ":la": Decimal(str(data.lat)),
                ":lo": Decimal(str(data.lon)),
                ":u": int(time.time() * 1000),
            },
            ConditionExpression="attribute_exists(ID_courier)",
        )

    async def get_nearby(self, lat: float, lon: float) -> dict[str, Any]:
        center_cell = generate_cell_index(lat, lon)
        cells_to_search = list(h3.grid_disk(center_cell, 1))

        # Dispara queries no DynamoDB em paralelo para todas as 7 células
        tasks = []
        for cell in cells_to_search:
            tasks.append(
                self.table.query(
                    IndexName="CellIndex",
                    KeyConditionExpression="cell_index = :ci",
                    FilterExpression="#s = :avail",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":ci": cell,
                        ":avail": CourierStatus.AVAILABLE.value
                    }
                )
            )

        responses = await asyncio.gather(*tasks)
        
        merged_items = []
        for resp in responses:
            for item in resp.get("Items", []):
                merged_items.append(_jsonify_item(item))

        # Ordenar os entregadores pela distância euclidiana para priorizar os mais próximos
        def get_dist(c):
            dlat = c["lat"] - lat
            dlon = c["lon"] - lon
            return dlat * dlat + dlon * dlon

        merged_items.sort(key=get_dist)

        return {"Items": merged_items, "Count": len(merged_items)}
