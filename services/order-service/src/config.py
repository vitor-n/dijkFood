import os
from dotenv import load_dotenv

load_dotenv()


def _database_url() -> str:
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_ENDPOINT")
    )
    if not url:
        # fallback só para desenvolvimento local — nunca credencial de produção aqui
        url = "postgresql+asyncpg://dijkfood_admin:localdev123@localhost:5432/dijkfood"
    return url


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    DYNAMO_TABLE:    str = os.environ.get("DYNAMO_TABLE", "CourierTracking")
    DYNAMO_ENDPOINT: str | None = os.environ.get("DYNAMO_ENDPOINT")

    POSTGRES_ENDPOINT: str = _database_url()

    TRACKING_SERVICE_ENDPOINT: str = os.environ.get(
        "TRACKING_SERVICE_ENDPOINT",
        "http://127.0.0.1:8002/",
    )
    FIREHOSE_STREAM_NAME: str = os.environ.get("FIREHOSE_STREAM_NAME", "PUT-S3-4k3iv")

    # Predição de ETA (camada preditiva) — caminho com timeout curto + fallback
    PREDICTION_SERVICE_ENDPOINT: str = os.environ.get(
        "PREDICTION_SERVICE_ENDPOINT", "http://127.0.0.1:8005/"
    )
    ETA_TIMEOUT: float = float(os.environ.get("ETA_TIMEOUT", "0.4"))
    ETA_FALLBACK_MIN: float = float(os.environ.get("ETA_FALLBACK_MIN", "35"))

settings = Settings()
