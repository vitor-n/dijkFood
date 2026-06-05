"""
routers.py  -  Rotas adicionais da core-api

Inclua no main.py:
    from .routers import router as extra_router
    app.include_router(extra_router)
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import async_session, Restaurant
from .new_models import Order, OrderEvent, Item, OutboxEvent
from .schemas import (
    OrderSummarySchema,
    OrderHistorySchema,
    OrderEventSchema,
    ItemCreateSchema,
    ItemResponseSchema,
)

router = APIRouter()


# ── Dependency ─────────────────────────────────────────────────────────────────

async def get_session():
    async with async_session() as session:
        yield session


# ── GET /admin/order  –  lista de pedidos de um usuário ───────────────────────

@router.get(
    "/admin/order",
    response_model=list[OrderSummarySchema],
    tags=["Admin – Orders"],
    summary="Lista todos os pedidos de um cliente",
)
async def list_orders(
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Retorna a lista de pedidos do cliente identificado por `user_id`,
    do mais recente para o mais antigo, com o estado atual de cada um.
    """
    result = await session.execute(
        select(Order)
        .where(Order.id_user == user_id)
        .options(selectinload(Order.last_state_rel))
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()

    return [
        OrderSummarySchema(
            id_order=o.id_order,
            created_at=o.created_at,
            id_restaurant=o.id_restaurant,
            id_courier=o.id_courier,
            last_state=o.last_state_rel.name,
        )
        for o in orders
    ]


# ── GET /admin/order/{id}  –  histórico de eventos de um pedido ───────────────

@router.get(
    "/admin/order/{order_id}",
    response_model=OrderHistorySchema,
    tags=["Admin – Orders"],
    summary="Histórico completo de eventos de um pedido",
)
async def get_order_history(
    order_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Retorna os dados do pedido e a lista cronológica de todos os seus
    eventos (transições de estado), incluindo o nome legível de cada estado.
    """
    result = await session.execute(
        select(Order)
        .where(Order.id_order == order_id)
        .options(
            selectinload(Order.last_state_rel),
            selectinload(Order.events).selectinload(OrderEvent.state_rel),
        )
    )
    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido {order_id} não encontrado.",
        )

    events = [
        OrderEventSchema(
            id_event=e.id_event,
            changed_at=e.changed_at,
            state=e.state_rel.name,
        )
        for e in order.events
    ]

    return OrderHistorySchema(
        id_order=order.id_order,
        created_at=order.created_at,
        id_restaurant=order.id_restaurant,
        id_user=order.id_user,
        id_courier=order.id_courier,
        last_state=order.last_state_rel.name,
        events=events,
    )


# ── POST /restaurants/{restaurant_id}/menu  –  adiciona item ao menu ──────────

@router.post(
    "/restaurants/{restaurant_id}/menu",
    response_model=ItemResponseSchema,
    status_code=status.HTTP_201_CREATED,
    tags=["Restaurants"],
    summary="Adiciona um item ao menu de um restaurante",
)
async def add_menu_item(
    restaurant_id: int,
    payload: ItemCreateSchema,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Cria um novo item no menu do restaurante especificado.
    Retorna o item criado com seu ID gerado pelo banco.
    """
    # Verifica se o restaurante existe
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Restaurante {restaurant_id} não encontrado.",
        )

    item = Item(name=payload.name, id_restaurant=restaurant_id)
    session.add(item)
    await session.flush()

    # Outbox transacional.
    item_data = {
        "id_item": item.id_item,
        "name": item.name,
        "id_restaurant": item.id_restaurant,
    }
    session.add(OutboxEvent(entidade="MenuItem", acao="CREATE", dados=item_data))

    await session.commit()
    await session.refresh(item)

    return ItemResponseSchema(
        id_item=item.id_item,
        name=item.name,
        id_restaurant=item.id_restaurant,
    )


# ── GET /restaurants/{restaurant_id}/menu  –  lista itens do menu ─────────────

@router.get(
    "/restaurants/{restaurant_id}/menu",
    response_model=list[ItemResponseSchema],
    tags=["Restaurants"],
    summary="Lista todos os itens do menu de um restaurante",
)
async def list_menu_items(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
):
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Restaurante {restaurant_id} não encontrado.",
        )

    result = await session.execute(
        select(Item).where(Item.id_restaurant == restaurant_id)
    )
    items = result.scalars().all()

    return [
        ItemResponseSchema(id_item=i.id_item, name=i.name, id_restaurant=i.id_restaurant)
        for i in items
    ]
