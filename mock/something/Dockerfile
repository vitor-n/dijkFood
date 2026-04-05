FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt

COPY simulator.py .

# ── API ────────────────────────────────────────────────────────────────────
ENV API_BASE_URL=http://localhost:8000

# ── Carga ──────────────────────────────────────────────────────────────────
# Cenários prontos: 10 (normal) | 50 (pico) | 200 (evento especial)
ENV ORDERS_PER_SECOND=10
ENV TOTAL_ORDERS=""
ENV MAX_CONCURRENT_ORDERS=200

# ── Delays de simulação (segundos) ────────────────────────────────────────
ENV DELAY_PREPARING_MIN=5
ENV DELAY_PREPARING_MAX=15
ENV DELAY_READY_MIN=5
ENV DELAY_READY_MAX=10

# ── Entregador ─────────────────────────────────────────────────────────────
ENV POSITION_REPORT_INTERVAL=0.1

CMD ["python", "simulator.py"]
