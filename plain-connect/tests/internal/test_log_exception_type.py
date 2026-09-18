"""The OTLP log handler must report exception types with the same identity
the span SDK uses: `record_exception` writes module-qualified names, so the
handler's `exception.type` attribute must match — otherwise one exception
class shows up under two names depending on which signal reported it."""

from __future__ import annotations

import logging

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogExporter,
    SimpleLogRecordProcessor,
)
from plain.connect.config import _QualifiedExceptionTypeLoggingHandler


class _CustomError(Exception):
    pass


def _export_exception_log(exc: BaseException) -> dict:
    """Log `exc` via logger.exception through the handler and return the
    exported OTel log record's attributes."""
    exporter = InMemoryLogExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = _QualifiedExceptionTypeLoggingHandler(logger_provider=provider)

    logger = logging.getLogger("test_log_exception_type")
    logger.addHandler(handler)
    try:
        try:
            raise exc
        except Exception:
            logger.exception("Something failed")
    finally:
        logger.removeHandler(handler)

    [log_data] = exporter.get_finished_logs()
    attributes = log_data.log_record.attributes
    assert attributes is not None
    return dict(attributes)


def test_custom_exception_type_is_module_qualified() -> None:
    attributes = _export_exception_log(_CustomError("boom"))
    assert attributes["exception.type"] == f"{_CustomError.__module__}._CustomError"
    # The rest of the stock exception attributes still come through.
    assert attributes["exception.message"] == "boom"
    assert "exception.stacktrace" in attributes


def test_builtin_exception_type_stays_bare() -> None:
    attributes = _export_exception_log(ValueError("boom"))
    assert attributes["exception.type"] == "ValueError"
