from __future__ import annotations

import logging
import threading

from opentelemetry import _logs, metrics, trace
from opentelemetry._logs._internal import ProxyLoggerProvider
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
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


class _ExporterLoopFilter(logging.Filter):
    """Block records that would feed back into OTLP export under failure.

    Two sources to suppress:

    1. The OpenTelemetry SDK's own namespace — its `failed to export`
       warnings would re-queue indefinitely.
    2. Anything emitted from inside an OTel SDK exporter thread (e.g.
       urllib3 connection errors raised by the OTLP HTTP exporter). The
       SDK names every exporter thread with an `Otel` prefix —
       `OtelBatch{Span,Log}RecordProcessor` for traces/logs, and
       `OtelPeriodicExportingMetricReader` for metrics — so matching on
       that prefix catches all three. Scoping to the thread, not the
       urllib3 namespace, lets user-code urllib3 logs flow through.

    See `opentelemetry/sdk/_shared_internal/__init__.py` (BatchProcessor)
    and `opentelemetry/sdk/metrics/export/__init__.py`
    (PeriodicExportingMetricReader) for the thread names.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            return False
        if threading.current_thread().name.startswith("Otel"):
            return False
        return True


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
            timeout=30,
            compression=Compression.Gzip,
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
            timeout=30,
            compression=Compression.Gzip,
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.DELTA,
            },
        )
        reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(metric_readers=[reader], resource=resource)
        metrics.set_meter_provider(meter_provider)

        # Logs
        if settings.CLOUD_EXPORT_LOGS:
            current_logger_provider = _logs.get_logger_provider()
            if current_logger_provider and not isinstance(
                current_logger_provider, ProxyLoggerProvider
            ):
                raise RuntimeError(
                    "A logger provider already exists."
                    " plain.cloud must be listed before plain.observer in INSTALLED_PACKAGES."
                )

            # Accept either a level name ("INFO") or an int (20).
            raw_level = settings.CLOUD_LOG_LEVEL
            if isinstance(raw_level, str):
                log_level = logging.getLevelName(raw_level.upper())
                if not isinstance(log_level, int):
                    raise ValueError(
                        f"CLOUD_LOG_LEVEL={raw_level!r} is not a valid logging level."
                    )
            else:
                log_level = int(raw_level)

            log_exporter = OTLPLogExporter(
                endpoint=f"{export_url}/v1/logs",
                headers=headers,
                timeout=30,
                compression=Compression.Gzip,
            )
            logger_provider = LoggerProvider(resource=resource)
            logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )
            _logs.set_logger_provider(logger_provider)

            handler = LoggingHandler(level=log_level, logger_provider=logger_provider)
            # Filter on the handler (not the loggers) so OTLP exporter and
            # HTTP-client diagnostics still reach the app's console/file
            # handlers — we only stop them from being re-exported, which
            # would loop under failure.
            handler.addFilter(_ExporterLoopFilter())

            # Plain's `configure_logging` sets `plain` and `app` to
            # propagate=False, so attaching only to root would miss them.
            # Attach to root for everything else (user `getLogger(__name__)`,
            # third-party libs).
            for name in ("", "plain", "app"):
                logging.getLogger(name).addHandler(handler)

            # Root defaults to WARNING. A library that uses
            # `logging.getLogger(__name__)` without setting its own level
            # inherits root's effective level — so INFO/DEBUG records get
            # dropped before the OTLP handler runs. Widen root just enough
            # to let CLOUD_LOG_LEVEL through; never narrow it.
            # NOTSET (0) on root already means "all messages processed",
            # so leave it alone in that case.
            root = logging.getLogger()
            if root.level != logging.NOTSET and root.level > log_level:
                root.setLevel(log_level)
