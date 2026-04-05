from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Restaurant(Base):
    __tablename__ = "restaurants"
    
    ID_restaurant = Column("id_restaurant", Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    lat = Column(Numeric(10, 8), nullable=False)
    lon = Column(Numeric(11, 8), nullable=False)
    H3_index = Column("h3_index", Integer, nullable=False)
    ID_cuisine_type = Column("id_cuisine_type", Integer, nullable=False)

class Order(Base):
    __tablename__ = "orders"
    
    ID_order = Column("id_order", Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False)
    ID_restaurant = Column("id_restaurant", Integer, nullable=False)
    ID_user = Column("id_user", Integer, nullable=False)
    ID_courier = Column("id_courier", Integer, nullable=False)
    ID_last_state = Column("id_last_state", Integer, nullable=False)

class OrderEvent(Base):
    __tablename__ = "orderevents"
    
    ID_event = Column("id_event", Integer, primary_key=True)
    changed_at = Column(DateTime, nullable=False)
    ID_order = Column("id_order", Integer, nullable=False)
    ID_state = Column("id_state", Integer, nullable=False)

class OrderCreationRequest(BaseModel):
    id_restaurant: int
    id_user: int
    #TODO: add items: list[int]

class OrderCreationResponse(BaseModel):
    id_order: int
    id_courier: int

class OrderUpdateRequest(BaseModel):
    id_order: int
    id_state: int
    #TODO: add items: list[int]

class OrderUpdateResponse(BaseModel):
    id_order: int
    id_state: int
