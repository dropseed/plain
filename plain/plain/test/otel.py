"""In-memory OpenTelemetry providers for tests.

The global tracer/meter providers are install-once per process, so both
helpers are idempotent — repeated calls return the same exporter/reader.
Plain projects using `plain.pytest` should reach for the `otel_spans` /
`otel_metrics` fixtures instead.
"""

from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

_span_exporter: InMemorySpanExporter | None = None
_metric_reader: InMemoryMetricReader | None = None


def install_test_tracer() -> InMemorySpanExporter:
    global _span_exporter
    if _span_exporter is None:
        _span_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
        trace.set_tracer_provider(provider)
    return _span_exporter


def install_test_meter() -> InMemoryMetricReader:
    global _metric_reader
    if _metric_reader is None:
        _metric_reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[_metric_reader])
        metrics.set_meter_provider(provider)
    return _metric_reader
