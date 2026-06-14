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
from .new_models import OutboxEvent, OrderItem, Item
from .schemas import OrderItemSchema, ItemSchema

from .config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cria o pool de conexões com o DynamoDB uma única vez para toda a execução da API
    session = aioboto3.Session()
    
    kwargs = {"region_name": settings.AWS_REGION}
    ep = (settings.DYNAMO_ENDPOINT or "").strip()
    if ep.startswith("http"):
        kwargs["endpoint_url"] = ep

    from botocore.config import Config
    boto_config = Config(max_pool_connections=200)
    kwargs["config"] = boto_config

    # Client do Dynamo
    async with session.resource("dynamodb", **kwargs) as dynamo_resource:
        app.state.dynamodb = dynamo_resource
        
        # Client do Firehose
        async with session.client("firehose", region_name=settings.AWS_REGION, config=boto_config) as firehose_client:
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
    await session.flush()

    # Outbox transacional: evento analítico gravado na MESMA transação.
    user_data = {**user.model_dump(), "id_user": new_user.id_user}
    session.add(OutboxEvent(entidade="User", acao="CREATE", dados=user_data))

    await session.commit()
    await session.refresh(new_user)
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
    await session.flush()

    # Outbox transacional.
    restaurant_data = {**restaurant.model_dump(), "id_restaurant": new_restaurant.id_restaurant}
    session.add(OutboxEvent(entidade="Restaurant", acao="CREATE", dados=restaurant_data))

    await session.commit()
    await session.refresh(new_restaurant)
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

    # Outbox transacional (mesma transação do cadastro do entregador).
    courier_data = {**courier.model_dump(exclude={"lat", "lon"}), "id_courier": courier_trimmed.id_courier}
    session.add(OutboxEvent(entidade="Courier", acao="CREATE", dados=courier_data))

    await session.commit()
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
    tags = ["Couriers"],
    included_methods = ["read", "read_multi", "update"]
))

# Endpoints CRUD para itens de pedido (OrderItems)
app.include_router(crud_router(
    session = get_session,
    model = OrderItem,
    create_schema = OrderItemSchema,
    update_schema = OrderItemSchema,
    select_schema = OrderItemSchema,
    path = "/order_items",
    tags = ["Order Items"]
))

# Endpoints CRUD global para itens de cardápio (Menu Items)
app.include_router(crud_router(
    session = get_session,
    model = Item,
    create_schema = ItemSchema,
    update_schema = ItemSchema,
    select_schema = ItemSchema,
    path = "/items",
    tags = ["Items"],
    included_methods=["read", "read_multi"] # Não expor create/delete/update se não for necessário
))

# Rotas adicionais: histórico de pedidos + menu de restaurantes
app.include_router(extra_router)
