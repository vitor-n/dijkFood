from fastapi import FastAPI, HTTPException, Depends
import httpx

from sqlalchemy import text, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from datetime import datetime
from urllib.parse import urljoin

from .models import (Order, OrderEvent, Restaurant,
                     OrderCreationRequest, OrderCreationResponse,
                     OrderUpdateRequest, OrderUpdateResponse)
from .config import settings

app = FastAPI(title="DijkFood Order Service")


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


engine = create_async_engine(settings.POSTGRES_ENDPOINT, pool_size = 15)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

@app.post("/order", response_model = OrderCreationResponse)
async def create_order(req: OrderCreationRequest, db: AsyncSession = Depends(get_db)):

    stmt = select(Restaurant).where(Restaurant.ID_restaurant == req.id_restaurant)
    restaurant_result = await db.execute(stmt)
    restaurant = restaurant_result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code = 404, detail = "Restaurant does not exist")
    
    print("restaurante existe:", restaurant.lat, restaurant.lon)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/nearby"),
            params = {"lat": float(restaurant.lat), "lon": float(restaurant.lon)},
            timeout = 2.0
        )

        if response.status_code == 422:
            print("Detalhes da rejeição do FastAPI:", response.text)

        response.raise_for_status()
        couriers = response.json()
    
        if len(couriers["Items"]) == 0:
            raise HTTPException(status_code = 404, detail = "Não temos entregadores disponíveis")
        
        #TODO: Implement proper loop
        for courier in couriers["Items"]:
            response = await client.patch(
                urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                json = {"ID_courier": courier["ID_courier"], "status": "BUSY"},
                timeout = 2.0
            )
            response.raise_for_status()
            print(response.json())
            break

    try:
        new_order = Order(
            created_at = datetime.now(),
            ID_restaurant = req.id_restaurant,
            ID_user = req.id_user,
            ID_courier = courier["ID_courier"],
            ID_last_state = 1
        )
        
        db.add(new_order)
        await db.flush() 
        
        new_event = OrderEvent(
            changed_at = new_order.created_at,
            ID_order = new_order.ID_order,
            ID_state = new_order.ID_last_state
        )
        
        db.add(new_event)
        await db.commit()
        
        return {"id_order": new_order.ID_order, "id_courier": courier["ID_courier"]}
        
    except Exception as e:

        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/order", response_model = OrderUpdateResponse)
async def update_order(
    req: OrderUpdateRequest, 
    db: AsyncSession = Depends(get_db)
):
    if req.id_state < 2 or req.id_state > 6:
        raise HTTPException(status_code = 400, detail = "Invalid state for update operation")
    try:
        with open("./order_update_query.sql") as f:
            sql_query = f.read()
        params = {"id_novo_estado": req.id_state, "id_pedido": req.id_order, "id_estado_antigo_esperado": req.id_state - 1}

        sql_query = text(sql_query)
        result = await db.execute(sql_query, params)
        
        updated_row = result.fetchone()
        
        if not updated_row:
            #TODO: add proper handling
            raise HTTPException(status_code=404, detail="Order not found or invalid status")
        
        if req.id_state == 6:
            stmt = select(Order).where(Order.ID_order == req.id_order)
            order_result = await db.execute(stmt)
            order = order_result.scalar_one_or_none()

            if order is None:
                raise HTTPException(status_code = 500, detail = "Internal error: failed to mark courier as available, aborting")
    
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    urljoin(settings.TRACKING_SERVICE_ENDPOINT, "tracking/status"),
                    json = {"ID_courier": order.ID_courier, "status": "AVAILABLE"},
                    timeout = 2.0
                )
                response.raise_for_status()

        await db.commit()
        row_dict = updated_row._mapping
        
        return {"id_order": row_dict["id_order"], "id_state": row_dict["id_state"]}
        
    except Exception as e:
        await db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
