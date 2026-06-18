from pydantic import BaseModel, ConfigDict
from datetime import datetime


# ── Items ──────────────────────────────────────────────────────────────────────

class ItemCreateSchema(BaseModel):
    """Payload para adicionar um item ao menu de um restaurante."""
    name: str


class ItemResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_item: int
    name: str
    id_restaurant: int

class ItemSchema(BaseModel):
    """Schema básico para CRUD global de Itens via FastCRUD"""
    model_config = ConfigDict(from_attributes=True)

    id_item: int | None = None
    name: str
    id_restaurant: int


# ── Order Items ───────────────────────────────────────────────────────────────

class OrderItemSchema(BaseModel):
    """Schema básico para CRUD de OrderItem."""
    model_config = ConfigDict(from_attributes=True)

    id_order_item: int | None = None
    price: float
    id_item: int
    id_order: int


class OrderItemResponseSchema(BaseModel):
    """Schema para retorno detalhado de item de pedido com nome do produto."""
    model_config = ConfigDict(from_attributes=True)

    id_order_item: int
    id_item: int
    name: str
    price: float


# ── Orders ─────────────────────────────────────────────────────────────────────

class OrderSummarySchema(BaseModel):
    """Resumo de um pedido na listagem do cliente."""
    model_config = ConfigDict(from_attributes=True)

    id_order: int
    created_at: datetime
    id_restaurant: int
    id_courier: int
    last_state: str          # nome do estado atual, e.g. "DELIVERED"


class OrderEventSchema(BaseModel):
    """Um evento (transição de estado) de um pedido."""
    model_config = ConfigDict(from_attributes=True)

    id_event: int
    changed_at: datetime
    state: str               # nome do estado


class OrderHistorySchema(BaseModel):
    """Histórico completo de um pedido."""
    model_config = ConfigDict(from_attributes=True)

    id_order: int
    created_at: datetime
    id_restaurant: int
    id_user: int
    id_courier: int
    last_state: str
    events: list[OrderEventSchema]
    items: list[OrderItemResponseSchema]
