from fastapi import FastAPI, Depends, HTTPException
from fastcrud import crud_router, FastCRUD
from sqlalchemy.ext.asyncio import AsyncSession
import boto3
import h3

from functools import lru_cache
from decimal import Decimal
import time

from .models import (User, UserSchema,
                   Restaurant, RestaurantSchema, 
                   Courier, CourierGeneralSchema, CourierCreationSchema,
                   async_session)

from .config import settings

#Aplicativo FastAPI
app = FastAPI()

async def get_session():
    async with async_session() as session:
        yield session

@lru_cache()
def get_courier_dynamo_table():
    db = boto3.resource(
        "dynamodb",
        region_name = settings.AWS_REGION
    )
    table = db.Table("CourierTracking")
    return table

#Mágica do fastcrud para gerar os endpoints básicos
app.include_router(crud_router(
    session = get_session,
    model = User,
    create_schema = UserSchema,
    update_schema = UserSchema,
    select_schema = UserSchema,
    path = "/users",
    tags = ["Users"]
))

app.include_router(crud_router(
    session = get_session,
    model = Restaurant,
    create_schema = RestaurantSchema,
    update_schema = RestaurantSchema,
    select_schema = RestaurantSchema,
    path = "/restaurants",
    tags = ["Restaurants"]
))

#Post personalizado do courier para guardar no dynamo tb
courier_crud = FastCRUD(Courier)

@app.post("/couriers", response_model = CourierGeneralSchema, tags=["Couriers"])
async def create_courier_custom(
    courier: CourierCreationSchema, 
    session: AsyncSession = Depends(get_session),
    courrier_table = Depends(get_courier_dynamo_table)
):
    
    db_dict = courier.model_dump(
        exclude={"lat", "lon"}
    )
    courier_trimmed = Courier(**db_dict)
   
    session.add(courier_trimmed)
    await session.flush() 

    try:
        courrier_table.put_item(
            Item = {
                "ID_courier": courier_trimmed.id_courier,
                "cell_index": h3.latlng_to_cell(courier.lat, courier.lon, 8),
                "lat": Decimal(str(courier.lat)),
                "lon": Decimal(str(courier.lon)),
                "status": "AVAILABLE",
                "updated_at": int(time.time() * 1000)
            }
        )
    except Exception as e:
        await session.rollback()        
        print(f"Erro ao salvar no DynamoDB: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Error while writing courier to dynamodb. Aborting."
        )

    await session.commit()
    return courier_trimmed

app.include_router(crud_router(
    session = get_session,
    model = Courier,
    create_schema = CourierGeneralSchema,
    update_schema = CourierGeneralSchema,
    select_schema = CourierGeneralSchema,
    path = "/couriers",
    tags = ["Couriers"]
))
