import os


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    # Camada analítica (Objetivo 3): consultas Athena sobre a tabela canônica.
    ATHENA_WORKGROUP: str = os.environ.get("ATHENA_WORKGROUP", "primary")
    GLUE_DATABASE: str = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
    EVENTS_TABLE: str = os.environ.get("EVENTS_TABLE", "events")

    # TTL do cache em memória dos resultados (s) — evita re-scan a cada page load.
    CACHE_TTL: int = int(os.environ.get("DASHBOARD_CACHE_TTL", "60"))
    QUERY_TIMEOUT: int = int(os.environ.get("ATHENA_QUERY_TIMEOUT", "45"))


settings = Settings()
