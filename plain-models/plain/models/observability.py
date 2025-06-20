from contextlib import contextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.semconv.attributes.db_attributes import (
    DB_NAMESPACE,
    DB_OPERATION_BATCH_SIZE,
    DB_OPERATION_NAME,
    DB_QUERY_TEXT,
    DB_SYSTEM_NAME,
)
from opentelemetry.semconv.attributes.network_attributes import (
    NETWORK_PEER_ADDRESS,
    NETWORK_PEER_PORT,
)
from opentelemetry.semconv.trace import DbSystemValues
from opentelemetry.trace import SpanKind

# Import the official suppression key used by OTel instrumentations when
# available (present once any opentelemetry-instrumentation-<pkg> is
# installed). Fallback to a module-local object so our own helpers can still
# reference it.
try:
    from opentelemetry.instrumentation.utils import (
        _SUPPRESS_INSTRUMENTATION_KEY as _SUPPRESS_KEY,
    )
except ImportError:  # instrumentation extras not installed
    _SUPPRESS_KEY = object()


tracer = trace.get_tracer("plain.models")


def db_system_for(vendor: str) -> str:  # noqa: D401 – simple helper
    """Return the canonical ``db.system.name`` value for a backend vendor."""

    return {
        "postgresql": DbSystemValues.POSTGRESQL.value,
        "mysql": DbSystemValues.MYSQL.value,
        "mariadb": DbSystemValues.MARIADB.value,
        "sqlite": DbSystemValues.SQLITE.value,
    }.get(vendor, vendor)


@contextmanager
def db_span(db, sql: Any, *, many: bool = False, batch_size: int | None = None):
    """Open an OpenTelemetry CLIENT span for a database query.

    All common attributes (`db.*`, `network.*`, etc.) are set automatically.
    """

    # Fast-exit if instrumentation suppression flag set in context.
    if otel_context.get_value(_SUPPRESS_KEY):
        yield None
        return

    # Derive operation keyword (SELECT, INSERT, …) if possible.
    operation: str | None = None
    if isinstance(sql, str):
        stripped = sql.lstrip()
        if stripped:
            operation = stripped.split()[0].upper()

    # Span name per OTel SQL guidance.
    if many:
        span_name = (operation or "EXECUTEMANY") + " many"
    else:
        span_name = operation or "QUERY"

    # Build attribute set.
    attrs: dict[str, Any] = {
        DB_SYSTEM_NAME: db_system_for(db.vendor),
        DB_NAMESPACE: db.settings_dict.get("NAME"),
        DB_QUERY_TEXT: sql if isinstance(sql, str) else str(sql),
    }

    if user := db.settings_dict.get("USER"):
        attrs["db.user"] = user

    if host := db.settings_dict.get("HOST"):
        attrs[NETWORK_PEER_ADDRESS] = host

    if port := db.settings_dict.get("PORT"):
        try:
            attrs[NETWORK_PEER_PORT] = int(port)
        except (TypeError, ValueError):
            pass

    # executemany: include batch size when >1 per semantic conventions.
    if batch_size and batch_size > 1:
        attrs[DB_OPERATION_BATCH_SIZE] = batch_size

    with tracer.start_as_current_span(span_name, kind=SpanKind.CLIENT) as span:
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value)

        if operation:
            span.set_attribute(DB_OPERATION_NAME, operation)

        yield span


# ---------------------------------------------------------------------------
# Context manager to suppress *all* instrumentation inside the block
# ---------------------------------------------------------------------------


@contextmanager
def suppress_tracing():
    """Temporarily disable **all** OpenTelemetry instrumentation.

    This sets the standard suppression flag recognised by every official
    instrumentation package, meaning *no spans* will be recorded for the
    duration of the context – not just database spans.
    """

    token = otel_context.attach(otel_context.set_value(_SUPPRESS_KEY, True))
    try:
        yield
    finally:
        otel_context.detach(token)


# ---------------------------------------------------------------------------
# Helper to disable DB spans temporarily
# ---------------------------------------------------------------------------


@contextmanager
def disable_db_spans():
    """Temporarily disable ``db_span`` within the current context.

    Useful when the application writes traces/spans back into the database to
    avoid generating additional spans for those internal operations.
    """

    # Retained for backward compatibility; internally delegates to
    # `suppress_tracing()` so that *all* instrumentation is suppressed, which
    # is usually what callers expect.
    with suppress_tracing():
        yield
