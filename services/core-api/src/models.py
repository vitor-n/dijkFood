import os
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from pydantic import BaseModel, ConfigDict, Field

from .config import settings

class Base(DeclarativeBase):
    pass

#Tabelas de tipos no banco de dados
class CuisineType(Base):
    __tablename__ = "cuisinetypes"
    ID_cuisine_type = Column("id_cuisine_type", Integer, primary_key=True)
    name = Column(String(128), nullable=False)

class VehicleType(Base):
    __tablename__ = "vehicletypes"
    ID_vehicle_type = Column("id_vehicle_type", Integer, primary_key=True)
    name = Column(String(128), nullable=False)

#Tabelas que o servico muda 
class User(Base):
    __tablename__ = "users"
    id_user = Column("id_user", Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False)
    phone = Column(String(15), nullable=False)
    lat = Column(Numeric(10, 8), nullable=False)
    lon = Column(Numeric(11, 8), nullable=False)

class Restaurant(Base):
    __tablename__ = "restaurants"
    id_restaurant = Column("id_restaurant", Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    lat = Column(Numeric(10, 8), nullable=False)
    lon = Column(Numeric(11, 8), nullable=False)
    h3_index = Column("h3_index", Integer, nullable=False)
    id_cuisine_type = Column("id_cuisine_type", Integer, ForeignKey("cuisinetypes.id_cuisine_type"), nullable=False)

class Courier(Base):
    __tablename__ = "courier"
    id_courier = Column("id_courier", Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    id_vehicle_type = Column("id_vehicle_type", Integer, ForeignKey("vehicletypes.id_vehicle_type"), nullable=False)

#Classes que determinam o tipo de dados que a API vai receber pra essas entidades
class UserSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_user: int | None = None
    name: str
    email: str
    phone: str
    lat: float
    lon: float

class RestaurantSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id_restaurant: int | None = None
    name: str
    lat: float
    lon: float
    h3_index: int = Field(alias="H3_index")
    id_cuisine_type: int = Field(alias="ID_cuisine_type")

class CourierGeneralSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id_courier: int | None = None
    name: str
    id_vehicle_type: int = Field(alias="ID_vehicle_type")

class CourierCreationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id_courier: int | None = None
    name: str
    lat: float
    lon: float
    id_vehicle_type: int = Field(alias="ID_vehicle_type")

engine = create_async_engine(settings.POSTGRES_ENDPOINT, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

