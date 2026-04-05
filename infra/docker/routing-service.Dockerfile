FROM python:3.12-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libgdal-dev \
        gdal-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/routing-service/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libgdal32 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

RUN adduser --disabled-password --no-create-home appuser && \
    mkdir -p /data && chown appuser:appuser /data

COPY infra/docker/scripts/download-graph.py ./download_graph.py
COPY services/routing-service/src/ ./src/

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/docs')" || exit 1

CMD ["sh", "-c", "python download_graph.py && uvicorn src.main:app --host 0.0.0.0 --port 8001 --workers 1"]
