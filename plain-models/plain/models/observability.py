import re
from contextlib import contextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.db_attributes import (
    DB_COLLECTION_NAME,
    DB_NAMESPACE,
    DB_OPERATION_BATCH_SIZE,
    DB_OPERATION_NAME,
    DB_QUERY_SUMMARY,
    DB_QUERY_TEXT,
    DB_SYSTEM,
)
from opentelemetry.semconv.attributes.network_attributes import (
    NETWORK_PEER_ADDRESS,
    NETWORK_PEER_PORT,
)
from opentelemetry.semconv.trace import DbSystemValues
from opentelemetry.trace import SpanKind, StatusCode

_SUPPRESS_KEY = object()

tracer = trace.get_tracer("plain.models")


def db_system_for(vendor: str) -> str:  # noqa: D401 – simple helper
    """Return the canonical ``db.system`` value for a backend vendor."""

    return {
        "postgresql": DbSystemValues.POSTGRESQL.value,
        "mysql": DbSystemValues.MYSQL.value,
        "mariadb": DbSystemValues.MARIADB.value,
        "sqlite": DbSystemValues.SQLITE.value,
    }.get(vendor, vendor)


def extract_operation_and_target(sql: str) -> tuple[str, str | None, str | None]:
    """Extract operation, table name, and collection from SQL.

    Returns: (operation, summary, collection_name)
    """
    sql_upper = sql.upper().strip()
    operation = sql_upper.split()[0] if sql_upper else "UNKNOWN"

    # Pattern to match quoted and unquoted identifiers
    # Matches: "quoted", `quoted`, [quoted], unquoted.name
    identifier_pattern = r'("([^"]+)"|`([^`]+)`|\[([^\]]+)\]|([\w.]+))'

    # Extract table/collection name based on operation
    collection_name = None
    summary = operation

    if operation in ("SELECT", "DELETE"):
        match = re.search(rf"FROM\s+{identifier_pattern}", sql, re.IGNORECASE)
        if match:
            collection_name = _clean_identifier(match.group(1))
            summary = f"{operation} {collection_name}"

    elif operation in ("INSERT", "REPLACE"):
        match = re.search(rf"INTO\s+{identifier_pattern}", sql, re.IGNORECASE)
        if match:
            collection_name = _clean_identifier(match.group(1))
            summary = f"{operation} {collection_name}"

    elif operation == "UPDATE":
        match = re.search(rf"UPDATE\s+{identifier_pattern}", sql, re.IGNORECASE)
        if match:
            collection_name = _clean_identifier(match.group(1))
            summary = f"{operation} {collection_name}"

    return operation, summary, collection_name


def _clean_identifier(identifier: str) -> str:
    """Remove quotes from SQL identifiers."""
    # Remove different types of SQL quotes
    if identifier.startswith('"') and identifier.endswith('"'):
        return identifier[1:-1]
    elif identifier.startswith("`") and identifier.endswith("`"):
        return identifier[1:-1]
    elif identifier.startswith("[") and identifier.endswith("]"):
        return identifier[1:-1]
    return identifier


@contextmanager
def db_span(db, sql: Any, *, many: bool = False, batch_size: int | None = None):
    """Open an OpenTelemetry CLIENT span for a database query.

    All common attributes (`db.*`, `network.*`, etc.) are set automatically.
    Follows OpenTelemetry semantic conventions for database instrumentation.
    """

    # Fast-exit if instrumentation suppression flag set in context.
    if otel_context.get_value(_SUPPRESS_KEY):
        yield None
        return

    sql = str(sql)  # Ensure SQL is a string for span attributes.

    # Extract operation and target information
    operation, summary, collection_name = extract_operation_and_target(sql)

    if many:
        summary = f"{summary} many"

    # Span name follows semantic conventions: {target} or {db.operation.name} {target}
    if summary:
        span_name = summary[:255]
    else:
        span_name = operation

    # Build attribute set following semantic conventions
    attrs: dict[str, Any] = {
        DB_SYSTEM: db_system_for(db.vendor),
        DB_NAMESPACE: db.settings_dict.get("NAME"),
        DB_QUERY_TEXT: sql,  # Already parameterized from Django/Plain
        DB_QUERY_SUMMARY: summary,
        DB_OPERATION_NAME: operation,
    }

    # Add collection name if detected
    if collection_name:
        attrs[DB_COLLECTION_NAME] = collection_name

    # Add user attribute (following newer conventions)
    if user := db.settings_dict.get("USER"):
        attrs["db.user"] = user

    # Network attributes
    if host := db.settings_dict.get("HOST"):
        attrs[NETWORK_PEER_ADDRESS] = host

    if port := db.settings_dict.get("PORT"):
        try:
            attrs[NETWORK_PEER_PORT] = int(port)
        except (TypeError, ValueError):
            pass

    # Batch size for executemany operations
    if batch_size and batch_size > 1:
        attrs[DB_OPERATION_BATCH_SIZE] = batch_size

    with tracer.start_as_current_span(span_name, kind=SpanKind.CLIENT) as span:
        # Set all non-None attributes
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value)

        try:
            yield span
        except Exception as e:
            # Record exception and set error status
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            raise


@contextmanager
def suppress_db_tracing():
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
