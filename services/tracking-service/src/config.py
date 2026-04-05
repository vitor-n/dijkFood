import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    AWS_REGION:      str = os.environ.get("AWS_REGION", "us-east-1")
    DYNAMO_TABLE:    str = os.environ.get("DYNAMO_TABLE", "CourierTracking")

    DYNAMO_ENDPOINT: str = os.environ.get("DYNAMO_ENDPOINT", None)

settings = Settings()