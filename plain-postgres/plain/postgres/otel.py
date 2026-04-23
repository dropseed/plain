from __future__ import annotations

import importlib.metadata
import re
import time
import traceback
import weakref
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import context as otel_context
from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.semconv.metrics.db_metrics import DB_CLIENT_OPERATION_DURATION

if TYPE_CHECKING:
    from opentelemetry.trace import Span
    from psycopg import Connection as PsycopgConnection

    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.sources import PoolSource

from opentelemetry.semconv._incubating.attributes.db_attributes import (
    DB_CLIENT_CONNECTION_POOL_NAME,
    DB_CLIENT_CONNECTION_STATE,
    DB_QUERY_PARAMETER_TEMPLATE,
    DbClientConnectionStateValues,
)
from opentelemetry.semconv._incubating.metrics.db_metrics import (
    DB_CLIENT_CONNECTION_COUNT,
    DB_CLIENT_CONNECTION_IDLE_MAX,
    DB_CLIENT_CONNECTION_IDLE_MIN,
    DB_CLIENT_CONNECTION_MAX,
    DB_CLIENT_CONNECTION_PENDING_REQUESTS,
    DB_CLIENT_CONNECTION_TIMEOUTS,
    DB_CLIENT_CONNECTION_USE_TIME,
    DB_CLIENT_CONNECTION_WAIT_TIME,
    DB_CLIENT_RESPONSE_RETURNED_ROWS,
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
    DbSystemNameValues,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.network_attributes import (
    NETWORK_PEER_ADDRESS,
    NETWORK_PEER_PORT,
)
from opentelemetry.semconv.attributes.server_attributes import (
    SERVER_ADDRESS,
    SERVER_PORT,
)
from opentelemetry.trace import SpanKind

from plain.runtime import settings
from plain.utils.otel import format_exception_type

# Use a stable string key so OpenTelemetry context APIs receive the expected type.
_SUPPRESS_KEY = "plain.postgres.suppress_db_tracing"

try:
    _package_version = importlib.metadata.version("plain.postgres")
except importlib.metadata.PackageNotFoundError:
    _package_version = "dev"

tracer = trace.get_tracer("plain.postgres", _package_version)

meter = metrics.get_meter("plain.postgres", version=_package_version)
query_duration_histogram = meter.create_histogram(
    name=DB_CLIENT_OPERATION_DURATION,
    unit="s",
    description="Duration of database client operations.",
)
returned_rows_histogram = meter.create_histogram(
    name=DB_CLIENT_RESPONSE_RETURNED_ROWS,
    unit="{row}",
    description="Number of rows returned by the operation.",
)
connection_wait_time_histogram = meter.create_histogram(
    name=DB_CLIENT_CONNECTION_WAIT_TIME,
    unit="s",
    description="The time it took to obtain an open connection from the pool.",
)
connection_use_time_histogram = meter.create_histogram(
    name=DB_CLIENT_CONNECTION_USE_TIME,
    unit="s",
    description="The time between borrowing a connection and returning it to the pool.",
)
connection_timeouts_counter = meter.create_counter(
    name=DB_CLIENT_CONNECTION_TIMEOUTS,
    unit="{timeout}",
    description="The number of connection timeouts that have occurred trying to obtain a connection from the pool.",
)

# WeakKeyDictionary prevents leaks if a conn is GC'd without explicit release().
_use_start: weakref.WeakKeyDictionary[PsycopgConnection[Any], float] = (
    weakref.WeakKeyDictionary()
)

DB_SYSTEM = DbSystemNameValues.POSTGRESQL.value


def record_connection_acquire(
    pool_name: str,
    conn: PsycopgConnection[Any],
    wait_seconds: float,
    checkout_time: float,
) -> None:
    connection_wait_time_histogram.record(
        wait_seconds, {DB_CLIENT_CONNECTION_POOL_NAME: pool_name}
    )
    _use_start[conn] = checkout_time


def record_connection_release(
    pool_name: str, conn: PsycopgConnection[Any], return_time: float
) -> None:
    start = _use_start.pop(conn, None)
    if start is None:
        return
    connection_use_time_histogram.record(
        return_time - start, {DB_CLIENT_CONNECTION_POOL_NAME: pool_name}
    )


def record_connection_timeout(pool_name: str) -> None:
    connection_timeouts_counter.add(1, {DB_CLIENT_CONNECTION_POOL_NAME: pool_name})


def register_pool_observables(pool_source: PoolSource) -> None:
    """Register observable gauges that read `pool.get_stats()` at collection time.

    Safe to call multiple times — the OTel SDK keeps one instrument per name.
    """
    pool_attrs = {DB_CLIENT_CONNECTION_POOL_NAME: pool_source.name}
    idle_attrs = {
        **pool_attrs,
        DB_CLIENT_CONNECTION_STATE: DbClientConnectionStateValues.IDLE.value,
    }
    used_attrs = {
        **pool_attrs,
        DB_CLIENT_CONNECTION_STATE: DbClientConnectionStateValues.USED.value,
    }

    def _count(_options: CallbackOptions) -> list[Observation]:
        stats = pool_source.get_stats()
        if stats is None:
            return []
        size = stats.get("pool_size", 0)
        available = stats.get("pool_available", 0)
        used = max(size - available, 0)
        return [
            Observation(used, used_attrs),
            Observation(available, idle_attrs),
        ]

    def _single(stats_key: str) -> Callable[[CallbackOptions], list[Observation]]:
        def callback(_options: CallbackOptions) -> list[Observation]:
            stats = pool_source.get_stats()
            if stats is None:
                return []
            return [Observation(stats.get(stats_key, 0), pool_attrs)]

        return callback

    meter.create_observable_up_down_counter(
        name=DB_CLIENT_CONNECTION_COUNT,
        unit="{connection}",
        description="The number of connections that are currently in state described by the state attribute.",
        callbacks=[_count],
    )
    for name, unit, description, stats_key in (
        (
            DB_CLIENT_CONNECTION_MAX,
            "{connection}",
            "The maximum number of open connections allowed.",
            "pool_max",
        ),
        (
            DB_CLIENT_CONNECTION_IDLE_MIN,
            "{connection}",
            "The minimum number of idle open connections allowed.",
            "pool_min",
        ),
        (
            DB_CLIENT_CONNECTION_IDLE_MAX,
            "{connection}",
            "The maximum number of idle open connections allowed.",
            "pool_max",
        ),
        (
            DB_CLIENT_CONNECTION_PENDING_REQUESTS,
            "{request}",
            "The number of current pending requests for an open connection.",
            "requests_waiting",
        ),
    ):
        meter.create_observable_up_down_counter(
            name=name,
            unit=unit,
            description=description,
            callbacks=[_single(stats_key)],
        )


def extract_operation_and_target(sql: str) -> tuple[str, str | None, str | None]:
    """Extract operation, table name, and collection from SQL.

    Returns: (operation, summary, collection_name)
    """
    sql_upper = sql.upper().strip()

    # Strip leading parentheses (e.g. UNION queries: "(SELECT ... UNION ...)")
    operation = sql_upper.lstrip("(").split()[0] if sql_upper else "UNKNOWN"

    # Pattern to match quoted and unquoted identifiers
    # Matches: "quoted" (PostgreSQL), unquoted.name
    identifier_pattern = r'("([^"]+)"|([\w.]+))'

    # Map operations to the SQL keyword that precedes the table name.
    keyword_by_operation = {
        "SELECT": "FROM",
        "DELETE": "FROM",
        "INSERT": "INTO",
        "UPDATE": "UPDATE",
    }

    # Extract table/collection name based on operation
    collection_name = None
    summary = operation

    keyword = keyword_by_operation.get(operation)
    if keyword:
        match = re.search(rf"{keyword}\s+{identifier_pattern}", sql, re.IGNORECASE)
        if match:
            collection_name = _clean_identifier(match.group(1))
            summary = f"{operation} {collection_name}"

    # Detect UNION queries
    if " UNION " in sql_upper and summary:
        summary = f"{summary} UNION"

    return operation, summary, collection_name


def _clean_identifier(identifier: str) -> str:
    """Remove quotes from SQL identifiers."""
    if identifier.startswith('"') and identifier.endswith('"'):
        return identifier[1:-1]
    return identifier


@contextmanager
def db_span(
    db: DatabaseConnection,
    sql: Any,
    *,
    many: bool = False,
    params: Any = None,
    row_count_provider: Callable[[], int] | None = None,
) -> Generator[Span | None]:
    """Open an OpenTelemetry CLIENT span for a database query.

    All common attributes (`db.*`, `network.*`, `server.*`, etc.) are set
    automatically. Follows OpenTelemetry semantic conventions for database
    instrumentation.

    If `row_count_provider` is given, `db.client.response.returned_rows` is
    recorded for SELECT operations using its return value (callable so the
    final count is read after streaming consumers finish iterating).
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

    # Single settings_dict read — the property delegates to source.config.
    cfg = db.settings_dict

    # Build attribute set following semantic conventions
    attrs: dict[str, Any] = {
        DB_SYSTEM_NAME: DB_SYSTEM,
        DB_NAMESPACE: cfg.get("DATABASE"),
        DB_QUERY_TEXT: sql,  # Already parameterized from Django/Plain
        DB_QUERY_SUMMARY: summary,
        DB_OPERATION_NAME: operation,
    }

    attrs.update(_get_code_attributes())

    # Add collection name if detected
    if collection_name:
        attrs[DB_COLLECTION_NAME] = collection_name

    # Server/network endpoint. `server.*` is the primary pair per current
    # semconv; `network.peer.*` is recommended supplementary.
    if host := cfg.get("HOST"):
        attrs[SERVER_ADDRESS] = host
        attrs[NETWORK_PEER_ADDRESS] = host

    if port := cfg.get("PORT"):
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            pass
        else:
            attrs[SERVER_PORT] = port_int
            attrs[NETWORK_PEER_PORT] = port_int

    # Add query parameters as attributes when DEBUG is True
    if settings.DEBUG and params is not None:
        # Convert params to appropriate format based on type
        if isinstance(params, dict):
            # Dictionary params (e.g., for named placeholders)
            for key, value in params.items():
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
        start = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            # record_exception + set_status(ERROR) handled by
            # start_as_current_span when the exception propagates out.
            span.set_attribute(ERROR_TYPE, format_exception_type(exc))
            raise
        duration_s = time.perf_counter() - start

        metric_attrs: dict[str, str] = {
            DB_SYSTEM_NAME: DB_SYSTEM,
            DB_OPERATION_NAME: operation,
        }
        if collection_name:
            metric_attrs[DB_COLLECTION_NAME] = collection_name
        query_duration_histogram.record(duration_s, metric_attrs)

        # Scope returned_rows to SELECT; rowcount for INSERT/UPDATE/DELETE
        # is rows-affected, which is a different semantic.
        if row_count_provider is not None and operation == "SELECT":
            count = row_count_provider()
            if count >= 0:
                returned_rows_histogram.record(count, metric_attrs)


@contextmanager
def suppress_db_tracing() -> Generator[None]:
    token = otel_context.attach(otel_context.set_value(_SUPPRESS_KEY, True))
    try:
        yield
    finally:
        otel_context.detach(token)


def _is_internal_frame(frame: traceback.FrameSummary) -> bool:
    """Return True if the frame is internal to plain.postgres or contextlib."""
    filepath = frame.filename
    if not filepath:
        return True
    if "/plain/postgres/" in filepath:
        return True
    if filepath.endswith("contextlib.py"):
        return True
    return False


def _get_code_attributes() -> dict[str, Any]:
    """Extract code context attributes for the current database query.

    Returns a dict of OpenTelemetry code attributes.
    """
    stack = traceback.extract_stack()

    # Find the first user code frame (outermost non-internal frame from the top of the call stack)
    for frame in reversed(stack):
        if _is_internal_frame(frame):
            continue

        attrs: dict[str, Any] = {
            CODE_FILE_PATH: frame.filename,
        }
        if frame.lineno:
            attrs[CODE_LINE_NUMBER] = frame.lineno
        if frame.name:
            attrs[CODE_FUNCTION_NAME] = frame.name
        if frame.colno:
            attrs[CODE_COLUMN_NUMBER] = frame.colno

        # Add full stack trace only in DEBUG mode (expensive)
        if settings.DEBUG:
            filtered_stack = [f for f in stack if not _is_internal_frame(f)]
            attrs[CODE_STACKTRACE] = "".join(traceback.format_list(filtered_stack))

        return attrs

    return {}
