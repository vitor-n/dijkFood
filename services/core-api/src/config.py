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
    
    POSTGRES_ENDPOINT: str = os.environ.get("POSTGRES_ENDPOINT", "postgresql+asyncpg://admin_user_prod:Ihateavroformat69@food-database.c7iyym0ymr45.us-east-1.rds.amazonaws.com:5432/production")

settings = Settings()
