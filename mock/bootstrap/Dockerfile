FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY mock/bootstrap/src/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mock/bootstrap/src/ /app/

ENV BASE_URL=http://localhost:8000 \
    NUM_USERS=1000 \
    NUM_RESTAURANTS=50 \
    NUM_COURIERS=3000 \
    BOOTSTRAP_CONCURRENCY=50 \
    BOOTSTRAP_MAX_RETRIES=3 \
    BOOTSTRAP_RETRY_BASE_DELAY=0.5

CMD ["python", "main.py"]
