from __future__ import annotations

import re
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import context as otel_context
from opentelemetry import trace

if TYPE_CHECKING:
    from opentelemetry.trace import Span

    from plain.models.backends.base.base import BaseDatabaseWrapper
from opentelemetry.semconv._incubating.attributes.db_attributes import (
    DB_QUERY_PARAMETER_TEMPLATE,
    DB_USER,
)
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_COLUMN_NUMBER,
    CODE_FILE_PATH,
    CODE_FUNCTION_NAME,
    CODE_LINE_NUMBER,
    CODE_STACKTRACE,
)
from opentelemetry.semconv.attributes.db_attributes import (
    DB_COLLECTION_NAME,
    DB_NAMESPACE,
    DB_OPERATION_NAME,
    DB_QUERY_SUMMARY,
    DB_QUERY_TEXT,
    DB_SYSTEM_NAME,
)
from opentelemetry.semconv.attributes.network_attributes import (
    NETWORK_PEER_ADDRESS,
    NETWORK_PEER_PORT,
)
from opentelemetry.semconv.trace import DbSystemValues
from opentelemetry.trace import SpanKind

from plain.runtime import settings

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
def db_span(
    db: BaseDatabaseWrapper, sql: Any, *, many: bool = False, params: Any = None
) -> Generator[Span | None, None, None]:
    """Open an OpenTelemetry CLIENT span for a database query.

    All common attributes (`db.*`, `network.*`, etc.) are set automatically.
    Follows OpenTelemetry semantic conventions for database instrumentation.
    """

    # Fast-exit if instrumentation suppression flag set in context.
    if otel_context.get_value(_SUPPRESS_KEY):  # type: ignore[arg-type]
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
        DB_SYSTEM_NAME: db_system_for(db.vendor),
        DB_NAMESPACE: db.settings_dict.get("NAME"),
        DB_QUERY_TEXT: sql,  # Already parameterized from Django/Plain
        DB_QUERY_SUMMARY: summary,
        DB_OPERATION_NAME: operation,
    }

    attrs.update(_get_code_attributes())

    # Add collection name if detected
    if collection_name:
        attrs[DB_COLLECTION_NAME] = collection_name

    # Add user attribute
    if user := db.settings_dict.get("USER"):
        attrs[DB_USER] = user

    # Network attributes
    if host := db.settings_dict.get("HOST"):
        attrs[NETWORK_PEER_ADDRESS] = host

    if port := db.settings_dict.get("PORT"):
        try:
            attrs[NETWORK_PEER_PORT] = int(port)
        except (TypeError, ValueError):
            pass

    # Add query parameters as attributes when DEBUG is True
    if settings.DEBUG and params is not None:
        # Convert params to appropriate format based on type
        if isinstance(params, dict):
            # Dictionary params (e.g., for named placeholders)
            for i, (key, value) in enumerate(params.items()):
                attrs[f"{DB_QUERY_PARAMETER_TEMPLATE}.{key}"] = str(value)
        elif isinstance(params, list | tuple):
            # Sequential params (e.g., for %s or ? placeholders)
            for i, value in enumerate(params):
                attrs[f"{DB_QUERY_PARAMETER_TEMPLATE}.{i + 1}"] = str(value)
        else:
            # Single param (rare but possible)
            attrs[f"{DB_QUERY_PARAMETER_TEMPLATE}.1"] = str(params)

    with tracer.start_as_current_span(
        span_name, kind=SpanKind.CLIENT, attributes=attrs
    ) as span:
        yield span
        span.set_status(trace.StatusCode.OK)


@contextmanager
def suppress_db_tracing() -> Generator[None, None, None]:
    token = otel_context.attach(otel_context.set_value(_SUPPRESS_KEY, True))  # type: ignore[arg-type]
    try:
        yield
    finally:
        otel_context.detach(token)


def _get_code_attributes() -> dict[str, Any]:
    """Extract code context attributes for the current database query.

    Returns a dict of OpenTelemetry code attributes.
    """
    stack = traceback.extract_stack()

    # Find the user code frame
    for frame in reversed(stack):
        filepath = frame.filename
        if not filepath:
            continue

        if "/plain/models/" in filepath:
            continue

        if filepath.endswith("contextlib.py"):
            continue

        # Found user code - build attributes dict
        attrs = {}

        if filepath:
            attrs[CODE_FILE_PATH] = filepath
        if frame.lineno:
            attrs[CODE_LINE_NUMBER] = frame.lineno
        if frame.name:
            attrs[CODE_FUNCTION_NAME] = frame.name
        if frame.colno:
            attrs[CODE_COLUMN_NUMBER] = frame.colno

        # Add full stack trace only in DEBUG mode (expensive)
        if settings.DEBUG:
            # Filter out internal frames from the stack trace
            filtered_stack = []
            for frame in stack:
                filepath = frame.filename
                if not filepath:
                    continue
                if "/plain/models/" in filepath:
                    continue
                if filepath.endswith("contextlib.py"):
                    continue
                filtered_stack.append(frame)

            attrs[CODE_STACKTRACE] = "".join(traceback.format_list(filtered_stack))

        return attrs

    return {}
