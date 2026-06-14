from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Numeric, DateTime, BigInteger, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class OutboxEvent(Base):
    """Transactional outbox: gravado na MESMA transação do pedido."""
    __tablename__ = "outbox_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    entidade = Column(String(64), nullable=False)
    acao = Column(String(32), nullable=False)
    dados = Column(JSONB, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    published_at = Column(TIMESTAMP(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, server_default=text("0"))
class Restaurant(Base):
    __tablename__ = "restaurants"

    ID_restaurant  = Column("id_restaurant", Integer, primary_key=True, autoincrement=True)
    name           = Column(String(128), nullable=False)
    lat            = Column(Numeric(10, 8), nullable=False)
    lon            = Column(Numeric(11, 8), nullable=False)
    H3_index       = Column("h3_index", BigInteger, nullable=False)  # H3 é 64-bit
    ID_cuisine_type = Column("id_cuisine_type", Integer, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    ID_order      = Column("id_order", Integer, primary_key=True, autoincrement=True)
    created_at    = Column(DateTime, nullable=False)
    ID_restaurant = Column("id_restaurant", Integer, nullable=False)
    ID_user       = Column("id_user", Integer, nullable=False)
    ID_courier    = Column("id_courier", Integer, nullable=False)
    ID_last_state = Column("id_last_state", Integer, nullable=False)


class OrderEvent(Base):
    __tablename__ = "orderevents"

    ID_event   = Column("id_event", Integer, primary_key=True, autoincrement=True)  # consistente com nextval
    changed_at = Column(DateTime, nullable=False)
    ID_order   = Column("id_order", Integer, nullable=False)
    ID_state   = Column("id_state", Integer, nullable=False)


class OrderItem(Base):
    __tablename__ = "orderitems"

    ID_order_item = Column("id_order_item", Integer, primary_key=True, autoincrement=True)
    price         = Column(Numeric(100, 2), nullable=False)
    ID_item       = Column("id_item", Integer, nullable=False)
    ID_order      = Column("id_order", Integer, nullable=False)


# --- Pydantic schemas ---

class OrderItemRequest(BaseModel):
    id_item: int
    price: float

class OrderCreationRequest(BaseModel):
    id_restaurant: int
    id_user: int
    items: list[OrderItemRequest] = []

class OrderCreationResponse(BaseModel):
    id_order: int
    id_courier: int
    eta_minutes: float | None = None
    eta_source: str | None = None

class OrderUpdateRequest(BaseModel):
    id_order: int
    id_state: int
    #TODO: add items: list[int]

class OrderUpdateResponse(BaseModel):
    id_order: int
    id_state: int