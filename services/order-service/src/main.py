from fastapi import FastAPI, HTTPException, Depends

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from datetime import datetime

from .models import (Order, OrderEvent,
                     OrderCreationRequest, OrderCreationResponse,
                     OrderUpdateRequest, OrderUpdateResponse)
from .config import settings

app = FastAPI(title="DjikFood Routing Service")

engine = create_async_engine(settings.POSTGRES_ENDPOINT, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

@app.post("/order", response_model = OrderCreationResponse)
async def create_order(req: OrderCreationRequest, db: AsyncSession = Depends(get_db)):
    #TODO: courrier matching
    try:
        new_order = Order(
            created_at = datetime.now(),
            ID_restaurant = req.id_restaurant,
            ID_user = req.id_user,
            ID_courier = 1,  #TODO: implement matching
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
        
        return {"id_order": new_order.ID_order}
        
    except Exception as e:

        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/order", response_model = OrderUpdateResponse)
async def update_order(req: OrderUpdateRequest, db: AsyncSession = Depends(get_db)):
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
        
        await db.commit()
        row_dict = updated_row._mapping
        
        return {"id_order": row_dict["id_order"], "id_state": row_dict["id_state"]}
        
    except Exception as e:
        await db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
