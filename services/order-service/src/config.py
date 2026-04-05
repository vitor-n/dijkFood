import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    AWS_REGION:        str = os.environ.get("AWS_REGION", "us-east-1")

    DYNAMO_TABLE:      str = os.environ.get("DYNAMO_TABLE", "CourierTracking")
    DYNAMO_ENDPOINT:   str = os.environ.get("DYNAMO_ENDPOINT", None)

    POSTGRES_ENDPOINT: str = os.environ.get("POSTGRES_ENDPOINT", "postgresql+asyncpg://admin_user_prod:Ihateavroformat69@food-database.c7iyym0ymr45.us-east-1.rds.amazonaws.com:5432/production")

settings = Settings()
