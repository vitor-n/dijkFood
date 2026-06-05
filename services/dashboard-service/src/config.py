import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    # Camada analítica (Glue + Athena sobre o S3 alimentado pelo Firehose)
    GLUE_DATABASE: str = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
    ATHENA_WORKGROUP: str = os.environ.get("ATHENA_WORKGROUP", "dijkfood-analytics")
    EVENTS_TABLE: str = os.environ.get("EVENTS_TABLE", "events")

    # Cache server-side dos indicadores (segundos) — o lake é near-real-time
    # (buffer do Firehose ~300s), então não há ganho em consultar a cada request.
    CACHE_TTL: int = int(os.environ.get("DASHBOARD_CACHE_TTL", "45"))

    # Janela default das consultas (dias)
    LOOKBACK_DAYS: int = int(os.environ.get("DASHBOARD_LOOKBACK_DAYS", "30"))


settings = Settings()
