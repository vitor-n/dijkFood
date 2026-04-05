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
