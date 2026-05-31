"""
Emissor assíncrono e LIMITADO de eventos analíticos (Objetivo 3).

Por que existe (em vez de BackgroundTasks soltas): sob o cenário `event`
(200 req/s) agendar uma task por pedido — cada uma fazendo HTTP de predição +
escrita no Firehose — acumula milhares de corrotinas no mesmo event loop do
order-service, podendo regredir justamente o SLA que queremos proteger.

Aqui o caminho quente só faz `emit()` = `put_nowait` O(1) numa fila LIMITADA
(descarta com contador se encher → backpressure real, nunca bloqueia/atrasa a
resposta). Um único worker em background:
  • drena a fila em lotes e faz `put_record_batch` no Firehose;
  • para eventos marcados (amostrados), enriquece com o ETA previsto chamando o
    prediction-service com concorrência limitada (semáforo) e timeout — então a
    predição também é totalmente contida, não explode em N chamadas/s.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

log = logging.getLogger("order-events")

_MAXQ = 50_000          # limite da fila (memória) → backpressure por descarte
_BATCH = 450            # PutRecordBatch aceita até 500 por chamada
_FLUSH_INTERVAL = 1.0   # s entre flushes quando a fila esvazia
_PREDICT_CONCURRENCY = 20

Predictor = Callable[[int | None, str | None], Awaitable[float | None]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class EventEmitter:
    def __init__(self, stream_name: str | None, city: str = "sao_paulo", sample_rate: float = 1.0):
        self.stream_name = (stream_name or "").strip()
        self.enabled = bool(self.stream_name)
        self.city = city
        self.sample_rate = sample_rate

        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAXQ)
        self._client = None
        self._predictor: Predictor | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._sem = asyncio.Semaphore(_PREDICT_CONCURRENCY)

        # Observabilidade (não afeta o caminho quente).
        self.dropped = self.sent = self.failed = 0

    # ── ligação ao client/predictor (no lifespan) ────────────────────────
    def bind(self, firehose_client, predictor: Predictor | None = None) -> None:
        self._client = firehose_client
        self._predictor = predictor

    async def start(self) -> None:
        if not self.enabled:
            log.warning("EventEmitter desativado (FIREHOSE_STREAM_NAME vazio).")
            return
        self._task = asyncio.create_task(self._run(), name="event-flusher")

    async def stop(self) -> None:
        if not self.enabled or self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except asyncio.TimeoutError:
            self._task.cancel()

    # ── caminho quente: nunca bloqueia, nunca levanta ────────────────────
    def emit(self, event: dict[str, Any], predict: bool = False) -> None:
        if not self.enabled:
            return
        event.setdefault("occurred_at", _now_iso())
        event.setdefault("city", self.city)
        if predict and self._predictor is not None and random.random() <= self.sample_rate:
            event["_predict"] = True
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped % 1000 == 1:
                log.warning("Fila de eventos cheia — %d descartados.", self.dropped)

    # ── background ───────────────────────────────────────────────────────
    async def _run(self) -> None:
        while not (self._stop.is_set() and self._queue.empty()):
            batch = await self._collect()
            if not batch:
                continue
            await self._enrich(batch)
            await self._flush(batch)

    async def _collect(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        try:
            batch.append(await asyncio.wait_for(self._queue.get(), timeout=_FLUSH_INTERVAL))
        except asyncio.TimeoutError:
            return batch
        while len(batch) < _BATCH:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _enrich(self, batch: list[dict[str, Any]]) -> None:
        # Remove o marcador interno de TODOS os eventos; prevê só os marcados.
        flagged = [e for e in batch if e.pop("_predict", False)]
        if not flagged or self._predictor is None:
            return
        await asyncio.gather(*[self._predict_one(e) for e in flagged], return_exceptions=True)

    async def _predict_one(self, event: dict[str, Any]) -> None:
        async with self._sem:  # concorrência de predição limitada
            try:
                event["predicted_eta_s"] = await self._predictor(
                    event.get("restaurant_id"), event.get("h3_cell")
                )
            except Exception:
                pass

    async def _flush(self, batch: list[dict[str, Any]]) -> None:
        records = [{"Data": (json.dumps(e, default=str) + "\n").encode("utf-8")} for e in batch]
        try:
            resp = await self._client.put_record_batch(
                DeliveryStreamName=self.stream_name, Records=records
            )
            failed = resp.get("FailedPutCount", 0)
            self.sent += len(records) - failed
            self.failed += failed
        except Exception as exc:  # best-effort: analítica nunca derruba a operação
            self.failed += len(records)
            log.warning("Falha ao enviar lote ao Firehose (%d): %s", len(records), exc)
