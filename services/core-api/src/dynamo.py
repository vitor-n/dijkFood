import aioboto3

from .config import settings

def dynamodb_resource():
    kwargs: dict = {"region_name": settings.AWS_REGION}
    ep = (settings.DYNAMO_ENDPOINT or "").strip()
    if ep.startswith("http"):
        kwargs["endpoint_url"] = ep
    
    session = aioboto3.Session()
    return session.resource("dynamodb", **kwargs)
