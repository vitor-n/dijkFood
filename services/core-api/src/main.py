from fastapi import FastAPI, Depends, HTTPException, Request
from fastcrud import crud_router, FastCRUD
from sqlalchemy.ext.asyncio import AsyncSession
import asyncpg
from contextlib import asynccontextmanager
import aioboto3
import h3

from functools import lru_cache
from decimal import Decimal
import time

from .models import (User, UserSchema,
                   Restaurant, RestaurantSchema, 
                   Courier, CourierGeneralSchema, CourierCreationSchema,
                   async_session)
from .routers import router as extra_router

from .config import settings

#Isso é para rodar o DDL e DML no banco
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Iniciando setup do banco de dados...")
    try:
        with open("sql/schema.sql", "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with open("sql/lookup-data.sql", "r", encoding="utf-8") as f:
            seed_sql = f.read()

        url = settings.POSTGRES_ENDPOINT.replace("+asyncpg", "")

        conn = await asyncpg.connect(url)
        try:
            await conn.execute(schema_sql)
            await conn.execute(seed_sql)
            print("Setup do banco de dados concluido com sucesso!")
        finally:
            await conn.close()
            
    except Exception as e:
        print(f"Erro ao inicializar o banco de dados: {e}")
        
    #Cria o pool de conexoes uma unica vez para toda a execução da API
    session = aioboto3.Session()
    
    kwargs = {"region_name": settings.AWS_REGION}
    ep = (settings.DYNAMO_ENDPOINT or "").strip()
    if ep.startswith("http"):
        kwargs["endpoint_url"] = ep

    async with session.resource("dynamodb", **kwargs) as dynamo_resource:
        app.state.dynamodb = dynamo_resource
        yield

#Aplicativo FastAPI
app = FastAPI(lifespan = lifespan)

@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}

async def get_session():
    async with async_session() as session:
        yield session

async def get_courier_dynamo_table(request: Request):
    db = request.app.state.dynamodb
    table = await db.Table("CourierTracking")
    return table

#Mágica do fastcrud para gerar os endpoints básicos
app.include_router(crud_router(
    session=get_session,
    model=User,
    create_schema=UserSchema,
    update_schema=UserSchema,
    select_schema=UserSchema,
    path="/users",
    tags=["Users"]
))

app.include_router(crud_router(
    session=get_session,
    model=Restaurant,
    create_schema=RestaurantSchema,
    update_schema=RestaurantSchema,
    select_schema=RestaurantSchema,
    path="/restaurants",
    tags=["Restaurants"]
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
        await courrier_table.put_item(
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

# Rotas adicionais: histórico de pedidos + menu de restaurantes
app.include_router(extra_router)
