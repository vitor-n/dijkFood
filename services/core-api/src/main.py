from fastapi import FastAPI
from fastcrud import crud_router
from .models import (User, UserSchema,
                   Restaurant, RestaurantSchema, 
                   Courier, CourierSchema, 
                   async_session)

#Aplicativo FastAPI
app = FastAPI()

async def get_session():
    async with async_session() as session:
        yield session

#Mágica do fastcrud para gerar os endpoints básicos
app.include_router(crud_router(
    session = get_session,
    model = User,
    create_schema = UserSchema,
    update_schema = UserSchema,
    path = "/users",
    tags = ["Users"]
))

app.include_router(crud_router(
    session = get_session,
    model = Restaurant,
    create_schema = RestaurantSchema,
    update_schema = RestaurantSchema,
    path = "/restaurants",
    tags = ["Restaurants"]
))

app.include_router(crud_router(
    session = get_session,
    model = Courier,
    create_schema = CourierSchema,
    update_schema = CourierSchema,
    path = "/couriers",
    tags = ["Couriers"]
))
