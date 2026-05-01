from __future__ import annotations

import importlib.metadata
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.semconv._incubating.metrics.messaging_metrics import (
    create_messaging_client_consumed_messages,
    create_messaging_client_operation_duration,
    create_messaging_client_sent_messages,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

from plain.utils.otel import format_exception_type

try:
    _package_version = importlib.metadata.version("plain.jobs")
except importlib.metadata.PackageNotFoundError:
    _package_version = "dev"

tracer = trace.get_tracer("plain.jobs", _package_version)
meter = metrics.get_meter("plain.jobs", version=_package_version)

sent_messages_counter = create_messaging_client_sent_messages(meter)
consumed_messages_counter = create_messaging_client_consumed_messages(meter)
operation_duration_histogram = create_messaging_client_operation_duration(meter)
queue_wait_duration_histogram = meter.create_histogram(
    name="plain.jobs.queue.wait.duration",
    unit="s",
    description="Time a job spent waiting in the queue before a worker picked it up.",
)


def record_span_error(
    span: trace.Span,
    exc: BaseException,
    metric_attributes: dict[str, Any],
) -> None:
    error_type = format_exception_type(exc)
    span.record_exception(exc)
    span.set_status(trace.StatusCode.ERROR)
    span.set_attribute(ERROR_TYPE, error_type)
    metric_attributes[ERROR_TYPE] = error_type
