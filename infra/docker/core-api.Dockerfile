FROM python:3.12-slim AS base

WORKDIR /app

RUN adduser --disabled-password --no-create-home appuser

COPY services/core-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/core-api/src/ ./src/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
