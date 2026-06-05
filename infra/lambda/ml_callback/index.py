"""
ml-callback — etapa final da pipeline gerenciada de retreino.

Recebe do Step Functions o S3 do artefato produzido pelo SageMaker Training Job,
"promove" o model.joblib para o local de serving (models/eta/model.joblib) e
aciona o prediction-service (ECS) para recarregar o modelo e rodar o batch de
demanda/anomalias — fechando o ciclo coleta → treino → implantação → batch.

Env:
    DATALAKE_BUCKET   — bucket do datalake (artefatos + previsões).
    MODEL_PREFIX      — prefixo de serving (default models/eta).
    PREDICTION_URL    — base http do prediction-service (via ALB), opcional.
"""
import io
import json
import os
import tarfile
import urllib.request
from urllib.parse import urlparse

import boto3

_s3 = boto3.client("s3")
_sm = boto3.client("sagemaker")
BUCKET = os.environ["DATALAKE_BUCKET"]
MODEL_PREFIX = os.environ.get("MODEL_PREFIX", "models/eta")
PREDICTION_URL = os.environ.get("PREDICTION_URL", "").rstrip("/")
MODEL_PACKAGE_GROUP = os.environ.get("MODEL_PACKAGE_GROUP", "")
SAGEMAKER_IMAGE = os.environ.get("SAGEMAKER_IMAGE", "")


def _promote(model_artifacts_uri: str) -> str:
    parsed = urlparse(model_artifacts_uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    obj = _s3.get_object(Bucket=bucket, Key=key)
    tar_bytes = obj["Body"].read()

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name.endswith("model.joblib")), None)
        if member is None:
            raise RuntimeError("model.joblib não encontrado no artefato do SageMaker")
        extracted = tar.extractfile(member).read()

    dest_key = f"{MODEL_PREFIX}/model.joblib"
    _s3.put_object(Bucket=BUCKET, Key=dest_key, Body=extracted)
    return f"s3://{BUCKET}/{dest_key}"


def _register_model(model_artifacts_uri: str) -> dict:
    """Registra a versão do modelo no SageMaker Model Registry (Model Package Group)."""
    if not (MODEL_PACKAGE_GROUP and SAGEMAKER_IMAGE and model_artifacts_uri):
        return {"skipped": True}
    try:
        resp = _sm.create_model_package(
            ModelPackageGroupName=MODEL_PACKAGE_GROUP,
            ModelPackageDescription="ETA RandomForest (treino gerenciado via Step Functions/SageMaker)",
            ModelApprovalStatus="Approved",
            InferenceSpecification={
                "Containers": [{
                    "Image": SAGEMAKER_IMAGE,
                    "ModelDataUrl": model_artifacts_uri,
                }],
                "SupportedContentTypes": ["application/json"],
                "SupportedResponseMIMETypes": ["application/json"],
            },
        )
        return {"model_package_arn": resp.get("ModelPackageArn")}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _ping(path: str) -> dict:
    if not PREDICTION_URL:
        return {"skipped": True}
    try:
        req = urllib.request.Request(PREDICTION_URL + path, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return {"status": resp.status}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def handler(event, _context):
    # O Step Functions injeta a saída do CreateTrainingJob.
    uri = (
        event.get("ModelArtifacts", {}).get("S3ModelArtifacts")
        or event.get("model_artifacts")
        or event.get("S3ModelArtifacts")
    )
    promoted = _promote(uri) if uri else None
    registry = _register_model(uri) if uri else {"skipped": True}

    reload_res = _ping("/model/reload")
    batch_res = _ping("/batch/run")

    return {
        "promoted_artifact": promoted,
        "model_registry": registry,
        "reload": reload_res,
        "batch": batch_res,
    }
