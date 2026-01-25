from __future__ import annotations

import logging
import threading
from queue import Empty, Full, Queue
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter

logger = logging.getLogger(__name__)


class BackgroundTraceExporter:
    """
    Queues complete traces for background export to an OTLP backend.

    Unlike BatchSpanProcessor (which batches individual spans as they complete),
    this receives complete traces after tail-based sampling decisions have been made.
    This enables sampling based on the full trace context (e.g., "export if any span errored").

    The exporter runs in a background thread to avoid blocking request responses.
    On shutdown, remaining traces are flushed before the process exits.
    """

    def __init__(
        self,
        exporter: SpanExporter,
        max_queue_size: int = 1000,
        flush_interval: float = 2.0,
    ):
        self._exporter = exporter
        self._queue: Queue[list[ReadableSpan]] = Queue(maxsize=max_queue_size)
        self._flush_interval = flush_interval
        self._shutdown_event = threading.Event()

        # Non-daemon thread so it can finish flushing on shutdown
        self._worker = threading.Thread(target=self._run, name="otel-trace-exporter")
        self._worker.start()

    def export(self, spans: list[ReadableSpan]) -> bool:
        """
        Queue spans for background export. Non-blocking.

        Returns True if queued successfully, False if queue is full or shutdown.
        """
        if self._shutdown_event.is_set():
            return False
        try:
            self._queue.put_nowait(spans)
            return True
        except Full:
            logger.warning(
                "OTLP export queue full, dropping %d spans",
                len(spans),
            )
            return False

    def _run(self) -> None:
        """Background worker that exports traces."""
        while not self._shutdown_event.is_set():
            batch: list[ReadableSpan] = []

            # Collect spans until flush interval or shutdown
            try:
                # Block until first item available
                first = self._queue.get(timeout=self._flush_interval)
                batch.extend(first)

                # Drain any additional queued traces without blocking
                while True:
                    try:
                        batch.extend(self._queue.get_nowait())
                    except Empty:
                        break

            except Empty:
                # Timeout with no items - continue loop
                continue

            # Export the batch
            if batch:
                self._do_export(batch)

        # Flush remaining on shutdown
        self._flush_remaining()

    def _do_export(self, spans: list[ReadableSpan]) -> None:
        """Export spans to the backend."""
        try:
            self._exporter.export(spans)
        except Exception:
            logger.exception("Failed to export %d spans to OTLP backend", len(spans))

    def _flush_remaining(self) -> None:
        """Export everything left in queue during shutdown."""
        remaining: list[ReadableSpan] = []
        while True:
            try:
                remaining.extend(self._queue.get_nowait())
            except Empty:
                break

        if remaining:
            logger.debug("Flushing %d remaining spans on shutdown", len(remaining))
            self._do_export(remaining)

    def shutdown(self, timeout: float = 5.0) -> None:
        """
        Signal shutdown and wait for flush to complete.

        Called automatically by TracerProvider.shutdown() via ObserverSpanProcessor.
        """
        self._shutdown_event.set()
        self._worker.join(timeout=timeout)

        if self._worker.is_alive():
            logger.warning("OTLP exporter thread did not finish within timeout")

        self._exporter.shutdown()
