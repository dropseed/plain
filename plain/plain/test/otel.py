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
    return _span_exporter


def install_test_meter() -> InMemoryMetricReader:
    global _metric_reader
    if _metric_reader is None:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        _metric_reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[_metric_reader])
        metrics.set_meter_provider(provider)
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
    """Metrics captured by `capture_metrics`, with small lookup conveniences."""

    def __init__(self, reader: InMemoryMetricReader) -> None:
        self._reader = reader

    def get_metrics_data(self) -> Any:
        return self._reader.get_metrics_data()

    def collect(self) -> None:
        self._reader.collect()

    def points(self, name: str) -> list[Any]:
        """Return all data points for the named metric."""
        data = self.get_metrics_data()
        if data is None:
            return []
        return [
            point
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
    observations on entry. Read with `.points(name)` or `.get_metrics_data()`.
    """
    reader = install_test_meter()
    reader.get_metrics_data()  # drain
    yield CapturedMetrics(reader)
