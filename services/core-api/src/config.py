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
    AWS_REGION:      str = os.environ.get("AWS_REGION", "us-east-1")
    
    DYNAMO_TABLE:    str = os.environ.get("DYNAMO_TABLE", "CourierTracking")
    DYNAMO_ENDPOINT: str = os.environ.get("DYNAMO_ENDPOINT", "dynamodb.us-east-1.amazonaws.com")
    
    POSTGRES_ENDPOINT: str = os.environ.get("POSTGRES_ENDPOINT", "postgresql+asyncpg://admin_user:Ihateavroformat69@dijkfood-db.cp2a4as0eh8g.us-east-1.rds.amazonaws.com:5432/production")
    FIREHOSE_STREAM_NAME: str = os.environ.get("FIREHOSE_STREAM_NAME", "PUT-S3-4k3iv")

settings = Settings()
