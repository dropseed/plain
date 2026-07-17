"""In-memory OpenTelemetry providers for tests.

The global tracer/meter providers are install-once per process, so both
install helpers are idempotent — repeated calls return the same
exporter/reader. Tests should use the `capture_spans` / `capture_metrics`
context managers.

The OpenTelemetry SDK imports are deferred into the install helpers so that
importing `plain.test` (e.g. for `Client`) doesn't pay the SDK import cost.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

_span_exporter: InMemorySpanExporter | None = None
_metric_reader: InMemoryMetricReader | None = None


def install_test_tracer() -> InMemorySpanExporter:
    global _span_exporter
    if _span_exporter is None:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        _span_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
        trace.set_tracer_provider(provider)
        if trace.get_tracer_provider() is not provider:
            # set_tracer_provider is one-shot: if another provider was
            # installed first (e.g. plain.connect exporting for real), the
            # call is silently ignored and every capture would come up empty
            # — while test traffic exports to the real backend. Fail loudly.
            _span_exporter = None
            raise RuntimeError(
                "A global tracer provider is already installed — disable it "
                "for tests (e.g. PLAIN_CONNECT_EXPORT_ENABLED=false) so spans "
                "can be captured."
            )
    return _span_exporter


def install_test_meter() -> InMemoryMetricReader:
    global _metric_reader
    if _metric_reader is None:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import Counter, Histogram, UpDownCounter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            AggregationTemporality,
            InMemoryMetricReader,
        )

        # Delta temporality so each collection only reports what happened
        # since the last one — that's what makes the drain-on-entry in
        # capture_metrics() actually isolate one test's metrics from the
        # counters accumulated by everything that ran before it.
        _metric_reader = InMemoryMetricReader(
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
            }
        )
        provider = MeterProvider(metric_readers=[_metric_reader])
        metrics.set_meter_provider(provider)
        if metrics.get_meter_provider() is not provider:
            _metric_reader = None
            raise RuntimeError(
                "A global meter provider is already installed — disable it "
                "for tests so metrics can be captured."
            )
    return _metric_reader


class CapturedSpans:
    """Spans captured by `capture_spans`, with small lookup conveniences."""

    def __init__(self, exporter: InMemorySpanExporter) -> None:
        self._exporter = exporter

    def get_finished_spans(self) -> tuple[Any, ...]:
        return self._exporter.get_finished_spans()

    def find(self, *, kind: Any = None, name: str | None = None) -> Any:
        """Return the first finished span matching the given kind and/or name."""
        for span in self.get_finished_spans():
            if kind is not None and span.kind != kind:
                continue
            if name is not None and span.name != name:
                continue
            return span
        raise LookupError(f"No span found matching kind={kind!r} name={name!r}")


class CapturedMetrics:
    """
    Metrics captured by `capture_metrics`.

    Synchronous instruments report with delta temporality, so each drain of
    the reader only returns what happened since the last one — drains are
    accumulated here so `points()` always reflects the whole block.
    """

    def __init__(self, reader: InMemoryMetricReader) -> None:
        self._reader = reader
        self._collected: list[Any] = []

    def _drain(self) -> None:
        data = self._reader.get_metrics_data()
        if data is not None:
            self._collected.append(data)

    def collect(self) -> None:
        """Force a collection — triggers observable instrument callbacks."""
        self._drain()

    def clear(self) -> None:
        """Forget the metrics captured so far in this block."""
        self._drain()
        self._collected.clear()

    def points(self, name: str) -> list[Any]:
        """Return all data points recorded for the named metric."""
        self._drain()
        return [
            point
            for data in self._collected
            for resource_metrics in data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
            if metric.name == name
            for point in metric.data.data_points
        ]


@contextmanager
def capture_spans() -> Generator[CapturedSpans]:
    """
    The OpenTelemetry spans emitted during the block.

        with capture_spans() as spans:
            Client().get("/")
        server_span = spans.find(kind=trace.SpanKind.SERVER)
    """
    exporter = install_test_tracer()
    exporter.clear()
    yield CapturedSpans(exporter)


@contextmanager
def capture_metrics() -> Generator[CapturedMetrics]:
    """
    The OpenTelemetry metrics emitted during the block. Drains prior
    observations on entry. Read with `.points(name)`.
    """
    reader = install_test_meter()
    reader.get_metrics_data()  # drain anything recorded before the block
    yield CapturedMetrics(reader)
