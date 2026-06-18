import json
from fastapi import Request
from .config import settings
from datetime import datetime, timezone

#Função pra rodar em background
async def send_to_firehose(request: Request, entidade: str, acao: str, dados: dict):
    firehose = request.app.state.firehose_client
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entidade": entidade,
        "acao": acao,
        "dados": dados
    }
    
    try:
        registro = json.dumps(payload, default=str) + "\n"
        await firehose.put_record(
            DeliveryStreamName=settings.FIREHOSE_STREAM_NAME,
            Record={"Data": registro.encode("utf-8")}
        )
    except Exception as e:
        print(f"Erro ao enviar para o Firehose: {e}")
