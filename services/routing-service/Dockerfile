FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/routing-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser --disabled-password --gecos "" appuser

COPY services/routing-service/src ./src

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz')" || exit 1

# 4 workers são seguros: o serviço é agora um proxy HTTP leve, sem grafo em memória
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
