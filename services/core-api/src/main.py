from fastapi import FastAPI
from fastcrud import crud_router
from models import (User, UserSchema,
                   Restaurant, RestaurantSchema, 
                   Courier, CourierSchema, 
                   async_session)

# FastAPI App
app = FastAPI()

# Geração automática dos Endpoints via FastCRUD
app.include_router(crud_router(
    session=async_session,
    model=User,
    create_schema=UserSchema,
    update_schema=UserSchema,
    path="/users",
    tags=["Users"]
))

app.include_router(crud_router(
    session=async_session,
    model=Restaurant,
    create_schema=RestaurantSchema,
    update_schema=RestaurantSchema,
    path="/restaurants",
    tags=["Restaurants"]
))

app.include_router(crud_router(
    session=async_session,
    model=Courier,
    create_schema=CourierSchema,
    update_schema=CourierSchema,
    path="/couriers",
    tags=["Couriers"]
))
