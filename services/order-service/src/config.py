import os
from dotenv import load_dotenv

load_dotenv()


def _database_url() -> str:
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_ENDPOINT")
        or "postgresql+asyncpg://dijkfood_admin:localdev123@localhost:5432/dijkfood"
    )


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    DYNAMO_TABLE:      str = os.environ.get("DYNAMO_TABLE", "CourierTracking")
    DYNAMO_ENDPOINT:   str = os.environ.get("DYNAMO_ENDPOINT", None)

    POSTGRES_ENDPOINT: str = os.environ.get("POSTGRES_ENDPOINT", "postgresql+asyncpg://admin_user_prod:Ihateavroformat69@food-database.c7iyym0ymr45.us-east-1.rds.amazonaws.com:5432/production")

    TRACKING_SERVICE_ENDPOINT: str = os.environ.get(
        "TRACKING_SERVICE_ENDPOINT",
        "http://127.0.0.1:8002/",
    )

    # Camada analítica (Objetivo 3): destino do Firehose. Vazio => dispatch no-op.
    FIREHOSE_STREAM_NAME: str = os.environ.get("FIREHOSE_STREAM_NAME", "")

    # Capacidade preditiva (Objetivo 3): vazio => sem chamada (usa fallback).
    PREDICTION_SERVICE_ENDPOINT: str = os.environ.get("PREDICTION_SERVICE_ENDPOINT", "")
    PREDICTION_TIMEOUT_S: float = float(os.environ.get("PREDICTION_TIMEOUT_S", "0.3"))
    # Fração de pedidos enriquecidos com ETA previsto (limita carga de predição).
    PREDICTION_SAMPLE_RATE: float = float(os.environ.get("PREDICTION_SAMPLE_RATE", "1.0"))
settings = Settings()
