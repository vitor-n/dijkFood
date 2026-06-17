import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    GLUE_DATABASE: str = os.environ.get("GLUE_DATABASE", "dijkfood_analytics")
    ATHENA_WORKGROUP: str = os.environ.get("ATHENA_WORKGROUP", "dijkfood-analytics")

    # Bucket do datalake (Firehose) — também guarda modelos e previsões
    DATALAKE_BUCKET: str = os.environ.get("DATALAKE_BUCKET", "")

    MODEL_PREFIX: str = os.environ.get("MODEL_PREFIX", "models/eta")
    PRED_PREFIX: str = os.environ.get("PRED_PREFIX", "predictions")

    # Janela de coleta para treino/forecast (dias)
    TRAIN_LOOKBACK_DAYS: int = int(os.environ.get("TRAIN_LOOKBACK_DAYS", "60"))

    # Treina automaticamente no startup se não houver modelo no S3
    AUTO_TRAIN_ON_START: bool = os.environ.get("AUTO_TRAIN_ON_START", "true").lower() in ("1", "true", "yes")

    # Recarrega o modelo do S3 periodicamente (a pipeline SageMaker pode republicar)
    MODEL_RELOAD_SECONDS: int = int(os.environ.get("MODEL_RELOAD_SECONDS", "900"))

    # Fallback de ETA (min) quando não há modelo nem histórico
    ETA_FALLBACK_MIN: float = float(os.environ.get("ETA_FALLBACK_MIN", "35"))

    MIN_TRAIN_SAMPLES: int = int(os.environ.get("MIN_TRAIN_SAMPLES", "40"))

    # Piso (s) p/ considerar uma entrega válida no treino do ETA e na detecção de
    # entregas lentas. O simulador comprime o ciclo de vida (entregas ~20-30 s),
    # então um piso de 60 s descartava TODAS as entregas — modelo e anomalias
    # ficavam sem dados. 15 s mantém o filtro de transições degeneradas sem matar
    # a base. Entregas reais (produção) ficam muito acima disso.
    MIN_DELIVERY_SECONDS: int = int(os.environ.get("MIN_DELIVERY_SECONDS", "15"))

    # Detecção de anomalias de demanda (z-score sobre a série temporal por região).
    # Bucket configurável: 60 min é o default honesto; para demonstrar picos numa
    # janela curta de simulação, reduza (ex.: 5) para gerar buckets suficientes.
    ANOMALY_BUCKET_MINUTES: int = int(os.environ.get("ANOMALY_BUCKET_MINUTES", "60"))
    ANOMALY_MIN_BUCKETS: int = int(os.environ.get("ANOMALY_MIN_BUCKETS", "6"))

    # Batch periódico (demanda + anomalias). 0 = desligado (roda só via /batch/run
    # ou pela pipeline gerenciada). >0 = a cada N segundos, para o dashboard
    # refletir anomalias automaticamente durante a demo.
    BATCH_INTERVAL_SECONDS: int = int(os.environ.get("BATCH_INTERVAL_SECONDS", "300"))


settings = Settings()
