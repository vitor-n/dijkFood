"""
Extensão de models.py com as tabelas que a core-api precisa ler/escrever
para histórico de pedidos e menu de restaurantes.
"""
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, TIMESTAMP
from sqlalchemy.orm import relationship

from .models import Base


class OrderState(Base):
    __tablename__ = "orderstate"
    id_state = Column("id_state", Integer, primary_key=True)
    name = Column(String(128), nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id_order = Column("id_order", Integer, primary_key=True)
    created_at = Column(TIMESTAMP, nullable=False)
    id_restaurant = Column("id_restaurant", Integer, ForeignKey("restaurants.id_restaurant"), nullable=False)
    id_user = Column("id_user", Integer, ForeignKey("users.id_user"), nullable=False)
    id_courier = Column("id_courier", Integer, ForeignKey("courier.id_courier"), nullable=False)
    id_last_state = Column("id_last_state", Integer, ForeignKey("orderstate.id_state"), nullable=False)

    # Relacionamentos para eager-loading conveniente
    last_state_rel = relationship("OrderState", foreign_keys=[id_last_state])
    events = relationship("OrderEvent", back_populates="order", order_by="OrderEvent.changed_at")


class OrderEvent(Base):
    __tablename__ = "orderevents"
    id_event = Column("id_event", Integer, primary_key=True)
    changed_at = Column(TIMESTAMP, nullable=False)
    id_order = Column("id_order", Integer, ForeignKey("orders.id_order"), nullable=False)
    id_state = Column("id_state", Integer, ForeignKey("orderstate.id_state"), nullable=False)

    order = relationship("Order", back_populates="events")
    state_rel = relationship("OrderState", foreign_keys=[id_state])


class Item(Base):
    __tablename__ = "items"
    id_item = Column("id_item", Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    id_restaurant = Column("id_restaurant", Integer, ForeignKey("restaurants.id_restaurant"), nullable=False)