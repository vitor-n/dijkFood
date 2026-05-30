FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libgdal-dev \
        gdal-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/routing-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    GRAPH_PATH=/app/data/sao_paulo.pkl

RUN apt-get update && \
    apt-get install -y --no-install-recommends libgdal32 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /data && chown appuser:appuser /data

# COPY infra/docker/scripts/download-graph.py ./download_graph.py
COPY services/routing-service/data ./data
COPY services/routing-service/src ./src

USER appuser

RUN ls -la /app/data && echo "LISTAGEM DE ARQUIVOS NA PASTA /app/data"

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz')" || exit 1

# CMD ["sh", "-c", "python download_graph.py && uvicorn src.main:app --host 0.0.0.0 --port 8001"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
