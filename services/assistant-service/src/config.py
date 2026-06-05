import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    GLUE_DATABASE: str = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
    ATHENA_WORKGROUP: str = os.environ.get("ATHENA_WORKGROUP", "dijkfood-analytics")
    DATALAKE_BUCKET: str = os.environ.get("DATALAKE_BUCKET", "")

    # Catálogo semântico (dicionário + few-shots) — opcionalmente vindo do S3
    SEMANTIC_PREFIX: str = os.environ.get("SEMANTIC_PREFIX", "semantic")

    # ── Bedrock (camada conversacional) ──
    # Habilitado quando há acesso ao Bedrock; caso contrário cai no motor
    # determinístico (intents → SQL parametrizado), sem nunca falhar.
    USE_BEDROCK: bool = os.environ.get("USE_BEDROCK", "true").lower() in ("1", "true", "yes")
    BEDROCK_REGION: str = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-east-1"))
    BEDROCK_MODEL_ID: str = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")

    # Segurança da execução de SQL
    MAX_ROWS: int = int(os.environ.get("ASSISTANT_MAX_ROWS", "200"))
    QUERY_TIMEOUT: float = float(os.environ.get("ASSISTANT_QUERY_TIMEOUT", "45"))


settings = Settings()
