from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks
from fastcrud import crud_router, FastCRUD
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
from .firehose import send_to_firehose

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

    # Client do Dynamo
    async with session.resource("dynamodb", **kwargs) as dynamo_resource:
        app.state.dynamodb = dynamo_resource
        
        # Client do Firehose
        async with session.client("firehose", region_name=settings.AWS_REGION) as firehose_client:
            app.state.firehose_client = firehose_client
            yield

#Aplicativo FastAPI
app = FastAPI(lifespan = lifespan)

@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}

async def get_session():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_courier_dynamo_table(request: Request):
    db = request.app.state.dynamodb
    table = await db.Table("CourierTracking")
    return table

#Sobreescreve endpoints básicos pra poder salvar dados no firehose
@app.post("/users", response_model=UserSchema, tags=["Users"])
async def create_user_custom(
    user: UserSchema,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    new_user = User(**user.model_dump())
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    # Prepara os dados para o Data Lake, removendo metadados do SQLAlchemy
    user_data = new_user.__dict__.copy()
    user_data.pop("_sa_instance_state", None)

    # Dispara para o Firehose em segundo plano
    background_tasks.add_task(
        send_to_firehose,
        request,
        "User",
        "CREATE",
        user_data
    )
    return new_user


@app.post("/restaurants", response_model=RestaurantSchema, tags=["Restaurants"])
async def create_restaurant_custom(
    restaurant: RestaurantSchema,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    new_restaurant = Restaurant(**restaurant.model_dump())
    session.add(new_restaurant)
    await session.commit()
    await session.refresh(new_restaurant)

    # Prepara os dados para o Data Lake, removendo metadados do SQLAlchemy
    restaurant_data = new_restaurant.__dict__.copy()
    restaurant_data.pop("_sa_instance_state", None)

    # Dispara para o Firehose em segundo plano
    background_tasks.add_task(
        send_to_firehose,
        request,
        "Restaurant",
        "CREATE",
        restaurant_data
    )
    return new_restaurant

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
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    courrier_table = Depends(get_courier_dynamo_table)
):
    
    db_dict = courier.model_dump(
        exclude={"lat", "lon"}
    )
    courier_trimmed = Courier(**db_dict)
   
    session.add(courier_trimmed)
    await session.flush() 

    start = time.perf_counter_ns()
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
        duration = time.perf_counter_ns() - start
        print(f"Escrever no Dynamo levou {duration // 1000000}ms.")
        raise HTTPException(
            status_code=500, 
            detail="Error while writing courier to dynamodb. Aborting."
        )
    duration = time.perf_counter_ns() - start
    print(f"Escrever no Dynamo levou {duration // 1000000}ms.")
    await session.commit()

    courier_data = courier_trimmed.__dict__.copy()
    courier_data.pop("_sa_instance_state", None)
    
    background_tasks.add_task(
        send_to_firehose, 
        request, 
        "Courier", 
        "CREATE", 
        courier_data
    )

    return courier_trimmed

@app.delete("/couriers/{id_courier}", tags=["Couriers"])
async def delete_courier_custom(
    id_courier: int,
    session: AsyncSession = Depends(get_session),
    courrier_table = Depends(get_courier_dynamo_table)
):
    # Garante que o entregador existe no banco de dados
    stmt = select(Courier).where(Courier.id_courier == id_courier)
    result = await session.execute(stmt)
    courier = result.scalar_one_or_none()

    if not courier:
        raise HTTPException(status_code=404, detail="Courier not found")

    # Inicia a remoção do banco 
    await session.delete(courier)
    await session.flush()

    # Remove do DynamoDB
    try:
        await courrier_table.delete_item(
            Key={
                "ID_courier": id_courier
            }
        )
    except Exception as e:
        await session.rollback()
        print(f"Erro ao remover do DynamoDB: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error while deleting courier from dynamodb. Aborting."
        )

    # Se tudo deu certo, commita a transação no banco
    await session.commit()
    return {"message": "Courier deleted successfully from SQL and DynamoDB"}

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
