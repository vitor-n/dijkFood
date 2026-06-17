import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    # Camada analítica (Glue + Athena sobre o S3 alimentado pelo Firehose)
    GLUE_DATABASE: str = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
    ATHENA_WORKGROUP: str = os.environ.get("ATHENA_WORKGROUP", "dijkfood-analytics")
    EVENTS_TABLE: str = os.environ.get("EVENTS_TABLE", "events")

    # ── Arquitetura Lambda (batch + speed) ────────────────────────────────────
    # Os indicadores históricos pesados são servidos das tabelas Parquet `mart_*`
    # (pré-agregadas de hora em hora pelo Glue) → varredura mínima, sub-segundo.
    # Só os indicadores "vivos" (pedidos abertos, entregadores ativos, volume da
    # hora corrente) batem na tabela crua `events`, e numa janela CURTA.
    MARTS_ENABLED: bool = os.environ.get("DASHBOARD_USE_MARTS", "true").lower() in ("1", "true", "yes")

    # Janela da SPEED layer (dias) — só os indicadores em tempo real varrem o cru.
    SPEED_LOOKBACK_DAYS: int = int(os.environ.get("DASHBOARD_SPEED_LOOKBACK_DAYS", "2"))

    # Janela (min) para considerar um entregador "ativo" (última posição reportada).
    COURIER_WINDOW_MIN: int = int(os.environ.get("DASHBOARD_COURIER_WINDOW_MIN", "30"))

    # Cache server-side dos indicadores (segundos). Como os marts atualizam de
    # hora em hora e o speed tem buffer Firehose de ~60s, não há ganho em
    # reconsultar a cada request.
    CACHE_TTL: int = int(os.environ.get("DASHBOARD_CACHE_TTL", "90"))

    # Janela default do FALLBACK cru (dias) — usada só quando os marts ainda não
    # foram materializados (ex.: primeira execução, antes do 1º job Glue).
    LOOKBACK_DAYS: int = int(os.environ.get("DASHBOARD_LOOKBACK_DAYS", "30"))

    # Bucket do datalake (lê as previsões publicadas pelo prediction-service)
    DATALAKE_BUCKET: str = os.environ.get("DATALAKE_BUCKET", "")

    # URL do assistente conversacional (no ALB) — o dashboard roda numa EC2 à parte
    ASSISTANT_URL: str = os.environ.get("ASSISTANT_URL", "/chat")


settings = Settings()
