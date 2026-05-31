import os


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    # Fonte de features (camada analítica): Athena sobre a tabela canônica.
    ATHENA_WORKGROUP: str = os.environ.get("ATHENA_WORKGROUP", "primary")
    GLUE_DATABASE: str = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
    EVENTS_TABLE: str = os.environ.get("EVENTS_TABLE", "events")
    QUERY_TIMEOUT: int = int(os.environ.get("ATHENA_QUERY_TIMEOUT", "60"))

    # Persistência do modelo treinado (data lake).
    MODEL_BUCKET: str = os.environ.get("MODEL_BUCKET", "")
    MODEL_KEY: str = os.environ.get("MODEL_KEY", "models/delivery_time/model.joblib")

    # Treina sozinho no startup se não houver modelo no S3 e houver dados.
    TRAIN_ON_STARTUP: bool = os.environ.get("TRAIN_ON_STARTUP", "true").lower() in ("1", "true", "yes")
    MIN_TRAIN_SAMPLES: int = int(os.environ.get("MIN_TRAIN_SAMPLES", "30"))


settings = Settings()
