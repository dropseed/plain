from __future__ import annotations

import atexit

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider, UpDownCounter
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, sampling
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.attributes import service_attributes

from plain.packages import PackageConfig, register_config
from plain.runtime import settings


@register_config
class Config(PackageConfig):
    package_label = "plaincloud"

    def ready(self) -> None:
        if not settings.CLOUD_EXPORT_ENABLED or not settings.CLOUD_EXPORT_TOKEN:
            return

        resource = Resource.create(
            {
                service_attributes.SERVICE_NAME: settings.NAME,
                service_attributes.SERVICE_VERSION: settings.VERSION,
            }
        )

        export_url = str(settings.CLOUD_EXPORT_URL).rstrip("/")
        headers = {"Authorization": f"Bearer {settings.CLOUD_EXPORT_TOKEN}"}

        # Traces
        current_provider = trace.get_tracer_provider()
        if current_provider and not isinstance(
            current_provider, trace.ProxyTracerProvider
        ):
            raise RuntimeError(
                "A tracer provider already exists."
                " plain.cloud must be listed before plain.observer in INSTALLED_PACKAGES."
            )

        span_exporter = OTLPSpanExporter(
            endpoint=f"{export_url}/v1/traces",
            headers=headers,
        )
        sampler = sampling.TraceIdRatioBased(settings.CLOUD_TRACE_SAMPLE_RATE)
        tracer_provider = TracerProvider(sampler=sampler, resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        # Metrics — use delta temporality so each export contains only the
        # increment since the last export, not a running total.  This makes
        # server-side aggregation (sum/avg in ClickHouse) straightforward.
        metric_exporter = OTLPMetricExporter(
            endpoint=f"{export_url}/v1/metrics",
            headers=headers,
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.DELTA,
            },
        )
        reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(metric_readers=[reader], resource=resource)
        metrics.set_meter_provider(meter_provider)

        atexit.register(tracer_provider.shutdown)
        atexit.register(meter_provider.shutdown)
