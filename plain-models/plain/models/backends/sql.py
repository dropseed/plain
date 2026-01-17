"""
PostgreSQL-specific SQL generation functions.

All functions in this module are stateless - they don't depend on connection state.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
from collections.abc import Callable, Iterable
from functools import lru_cache, partial
from typing import TYPE_CHECKING, Any

from psycopg.types import numeric
from psycopg.types.json import Jsonb

from plain.models.backends.utils import split_tzname_delta
from plain.models.constants import OnConflict
from plain.models.db import NotSupportedError
from plain.utils import timezone
from plain.utils.regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from plain.models.fields import Field


# Integer field safe ranges by internal_type.
INTEGER_FIELD_RANGES: dict[str, tuple[int, int]] = {
    "SmallIntegerField": (-32768, 32767),
    "IntegerField": (-2147483648, 2147483647),
    "BigIntegerField": (-9223372036854775808, 9223372036854775807),
    "PositiveBigIntegerField": (0, 9223372036854775807),
    "PositiveSmallIntegerField": (0, 32767),
    "PositiveIntegerField": (0, 2147483647),
    "PrimaryKeyField": (-9223372036854775808, 9223372036854775807),
}

# Mapping of Field.get_internal_type() to the data type for Cast().
CAST_DATA_TYPES: dict[str, str] = {
    "PrimaryKeyField": "bigint",
}

# CharField data type when max_length isn't provided.
CAST_CHAR_FIELD_WITHOUT_MAX_LENGTH: str | None = "varchar"

# Start and end points for window expressions.
PRECEDING: str = "PRECEDING"
FOLLOWING: str = "FOLLOWING"
UNBOUNDED_PRECEDING: str = "UNBOUNDED " + PRECEDING
UNBOUNDED_FOLLOWING: str = "UNBOUNDED " + FOLLOWING
CURRENT_ROW: str = "CURRENT ROW"

# Prefix for EXPLAIN queries.
EXPLAIN_PREFIX: str = "EXPLAIN"
EXPLAIN_OPTIONS = frozenset(
    [
        "ANALYZE",
        "BUFFERS",
        "COSTS",
        "SETTINGS",
        "SUMMARY",
        "TIMING",
        "VERBOSE",
        "WAL",
    ]
)
SUPPORTED_EXPLAIN_FORMATS: set[str] = {"JSON", "TEXT", "XML", "YAML"}

# PostgreSQL integer type mapping for psycopg.
INTEGERFIELD_TYPE_MAP = {
    "SmallIntegerField": numeric.Int2,
    "IntegerField": numeric.Int4,
    "BigIntegerField": numeric.Int8,
    "PositiveSmallIntegerField": numeric.Int2,
    "PositiveIntegerField": numeric.Int4,
    "PositiveBigIntegerField": numeric.Int8,
}

# Maximum length of an identifier (63 by default in PostgreSQL).
MAX_NAME_LENGTH: int = 63

# Value to use during INSERT to specify that a field should use its default value.
PK_DEFAULT_VALUE: str = "DEFAULT"

# SQL clause to make a constraint "initially deferred" during CREATE TABLE.
DEFERRABLE_SQL: str = " DEFERRABLE INITIALLY DEFERRED"

# EXTRACT format validation pattern.
_EXTRACT_FORMAT_RE = _lazy_re_compile(r"[A-Z_]+")


@lru_cache
def get_json_dumps(
    encoder: type[json.JSONEncoder] | None,
) -> Callable[..., str]:
    if encoder is None:
        return json.dumps
    return partial(json.dumps, cls=encoder)


def quote_name(name: str) -> str:
    """
    Return a quoted version of the given table, index, or column name.
    Does not quote the given name if it's already been quoted.
    """
    if name.startswith('"') and name.endswith('"'):
        return name  # Quoting once is enough.
    return f'"{name}"'


def date_extract_sql(
    lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
) -> tuple[str, list[Any] | tuple[Any, ...]]:
    """
    Given a lookup_type of 'year', 'month', or 'day', return the SQL that
    extracts a value from the given date field field_name.
    """
    # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-EXTRACT
    if lookup_type == "week_day":
        # PostgreSQL DOW returns 0=Sunday, 6=Saturday; we return 1=Sunday, 7=Saturday.
        return f"EXTRACT(DOW FROM {sql}) + 1", params
    elif lookup_type == "iso_week_day":
        return f"EXTRACT(ISODOW FROM {sql})", params
    elif lookup_type == "iso_year":
        return f"EXTRACT(ISOYEAR FROM {sql})", params

    lookup_type = lookup_type.upper()
    if not _EXTRACT_FORMAT_RE.fullmatch(lookup_type):
        raise ValueError(f"Invalid lookup type: {lookup_type!r}")
    return f"EXTRACT({lookup_type} FROM {sql})", params


def _prepare_tzname_delta(tzname: str) -> str:
    tzname, sign, offset = split_tzname_delta(tzname)
    if offset:
        sign = "-" if sign == "+" else "+"
        return f"{tzname}{sign}{offset}"
    return tzname


def _convert_sql_to_tz(
    sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
) -> tuple[str, list[Any] | tuple[Any, ...]]:
    if tzname:
        tzname_param = _prepare_tzname_delta(tzname)
        return f"{sql} AT TIME ZONE %s", (*params, tzname_param)
    return sql, params


def date_trunc_sql(
    lookup_type: str,
    sql: str,
    params: list[Any] | tuple[Any, ...],
    tzname: str | None = None,
) -> tuple[str, tuple[Any, ...]]:
    """
    Given a lookup_type of 'year', 'month', or 'day', return the SQL that
    truncates the given date or datetime field field_name to a date object
    with only the given specificity.

    If `tzname` is provided, the given value is truncated in a specific timezone.
    """
    sql, params = _convert_sql_to_tz(sql, params, tzname)
    # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-TRUNC
    return f"DATE_TRUNC(%s, {sql})", (lookup_type, *params)


def datetime_cast_date_sql(
    sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
) -> tuple[str, list[Any] | tuple[Any, ...]]:
    """Return the SQL to cast a datetime value to date value."""
    sql, params = _convert_sql_to_tz(sql, params, tzname)
    return f"({sql})::date", params


def datetime_cast_time_sql(
    sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
) -> tuple[str, list[Any] | tuple[Any, ...]]:
    """Return the SQL to cast a datetime value to time value."""
    sql, params = _convert_sql_to_tz(sql, params, tzname)
    return f"({sql})::time", params


def datetime_extract_sql(
    lookup_type: str,
    sql: str,
    params: list[Any] | tuple[Any, ...],
    tzname: str | None,
) -> tuple[str, list[Any] | tuple[Any, ...]]:
    """
    Given a lookup_type of 'year', 'month', 'day', 'hour', 'minute', or
    'second', return the SQL that extracts a value from the given
    datetime field field_name.
    """
    sql, params = _convert_sql_to_tz(sql, params, tzname)
    if lookup_type == "second":
        # Truncate fractional seconds.
        return f"EXTRACT(SECOND FROM DATE_TRUNC(%s, {sql}))", ("second", *params)
    return date_extract_sql(lookup_type, sql, params)


def datetime_trunc_sql(
    lookup_type: str,
    sql: str,
    params: list[Any] | tuple[Any, ...],
    tzname: str | None,
) -> tuple[str, tuple[Any, ...]]:
    """
    Given a lookup_type of 'year', 'month', 'day', 'hour', 'minute', or
    'second', return the SQL that truncates the given datetime field
    field_name to a datetime object with only the given specificity.
    """
    sql, params = _convert_sql_to_tz(sql, params, tzname)
    # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-TRUNC
    return f"DATE_TRUNC(%s, {sql})", (lookup_type, *params)


def time_extract_sql(
    lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
) -> tuple[str, list[Any] | tuple[Any, ...]]:
    """
    Given a lookup_type of 'hour', 'minute', or 'second', return the SQL
    that extracts a value from the given time field field_name.
    """
    if lookup_type == "second":
        # Truncate fractional seconds.
        return f"EXTRACT(SECOND FROM DATE_TRUNC(%s, {sql}))", ("second", *params)
    return date_extract_sql(lookup_type, sql, params)


def time_trunc_sql(
    lookup_type: str,
    sql: str,
    params: list[Any] | tuple[Any, ...],
    tzname: str | None = None,
) -> tuple[str, tuple[Any, ...]]:
    """
    Given a lookup_type of 'hour', 'minute' or 'second', return the SQL
    that truncates the given time or datetime field field_name to a time
    object with only the given specificity.

    If `tzname` is provided, the given value is truncated in a specific timezone.
    """
    sql, params = _convert_sql_to_tz(sql, params, tzname)
    return f"DATE_TRUNC(%s, {sql})::time", (lookup_type, *params)


def distinct_sql(
    fields: list[str], params: list[Any] | tuple[Any, ...]
) -> tuple[list[str], list[Any]]:
    """
    Return an SQL DISTINCT clause which removes duplicate rows from the
    result set. If any fields are given, only check the given fields for
    duplicates.
    """
    if fields:
        params = [param for param_list in params for param in param_list]
        return (["DISTINCT ON ({})".format(", ".join(fields))], params)
    else:
        return ["DISTINCT"], []


def for_update_sql(
    nowait: bool = False,
    skip_locked: bool = False,
    of: tuple[str, ...] = (),
    no_key: bool = False,
) -> str:
    """Return the FOR UPDATE SQL clause to lock rows for an update operation."""
    return "FOR{} UPDATE{}{}{}".format(
        " NO KEY" if no_key else "",
        " OF {}".format(", ".join(of)) if of else "",
        " NOWAIT" if nowait else "",
        " SKIP LOCKED" if skip_locked else "",
    )


def limit_offset_sql(low_mark: int | None, high_mark: int | None) -> str:
    """Return LIMIT/OFFSET SQL clause."""
    offset = low_mark or 0
    if high_mark is not None:
        limit = high_mark - offset
    else:
        limit = None
    return " ".join(
        sql
        for sql in (
            ("LIMIT %d" % limit) if limit else None,  # noqa: UP031
            ("OFFSET %d" % offset) if offset else None,  # noqa: UP031
        )
        if sql
    )


def lookup_cast(lookup_type: str, internal_type: str | None = None) -> str:
    """
    Return the string to use in a query when performing lookups
    ("contains", "like", etc.). It should contain a '%s' placeholder for
    the column being searched against.
    """
    lookup = "%s"

    if lookup_type == "isnull" and internal_type in (
        "CharField",
        "EmailField",
        "TextField",
    ):
        return "%s::text"

    # Cast text lookups to text to allow things like filter(x__contains=4)
    if lookup_type in (
        "iexact",
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
        "regex",
        "iregex",
    ):
        if internal_type == "GenericIPAddressField":
            lookup = "HOST(%s)"
        else:
            lookup = "%s::text"

    # Use UPPER(x) for case-insensitive lookups; it's faster.
    if lookup_type in ("iexact", "icontains", "istartswith", "iendswith"):
        lookup = f"UPPER({lookup})"

    return lookup


def return_insert_columns(fields: list[Field]) -> tuple[str, tuple[Any, ...]]:
    """Return the RETURNING clause SQL and params to append to an INSERT query."""
    if not fields:
        return "", ()
    columns = [
        f"{quote_name(field.model.model_options.db_table)}.{quote_name(field.column)}"
        for field in fields
    ]
    return "RETURNING {}".format(", ".join(columns)), ()


def bulk_insert_sql(fields: list[Field], placeholder_rows: list[list[str]]) -> str:
    """Return the SQL for bulk inserting rows."""
    placeholder_rows_sql = (", ".join(row) for row in placeholder_rows)
    values_sql = ", ".join(f"({sql})" for sql in placeholder_rows_sql)
    return "VALUES " + values_sql


def regex_lookup(lookup_type: str) -> str:
    """
    Return the string to use in a query when performing regular expression
    lookups (using "regex" or "iregex").
    """
    # PostgreSQL uses ~ for regex and ~* for case-insensitive regex
    if lookup_type == "regex":
        return "%s ~ %s"
    return "%s ~* %s"


def prep_for_like_query(x: str) -> str:
    """Prepare a value for use in a LIKE query."""
    return str(x).replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def adapt_integerfield_value(
    value: int | Any | None, internal_type: str
) -> int | Any | None:
    from plain.models.expressions import ResolvableExpression

    if value is None or isinstance(value, ResolvableExpression):
        return value
    return INTEGERFIELD_TYPE_MAP[internal_type](value)


def adapt_ipaddressfield_value(
    value: str | None,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """
    Transform a string representation of an IP address into the expected
    type for the backend driver.
    """
    if value:
        return ipaddress.ip_address(value)
    return None


def adapt_json_value(value: Any, encoder: type[json.JSONEncoder] | None) -> Jsonb:
    return Jsonb(value, dumps=get_json_dumps(encoder))


def year_lookup_bounds_for_date_field(
    value: int, iso_year: bool = False
) -> list[datetime.date]:
    """
    Return a two-elements list with the lower and upper bound to be used
    with a BETWEEN operator to query a DateField value using a year lookup.

    `value` is an int, containing the looked-up year.
    If `iso_year` is True, return bounds for ISO-8601 week-numbering years.
    """
    if iso_year:
        first = datetime.date.fromisocalendar(value, 1, 1)
        second = datetime.date.fromisocalendar(value + 1, 1, 1) - datetime.timedelta(
            days=1
        )
    else:
        first = datetime.date(value, 1, 1)
        second = datetime.date(value, 12, 31)
    return [first, second]


def year_lookup_bounds_for_datetime_field(
    value: int, iso_year: bool = False
) -> list[datetime.datetime]:
    """
    Return a two-elements list with the lower and upper bound to be used
    with a BETWEEN operator to query a DateTimeField value using a year lookup.

    `value` is an int, containing the looked-up year.
    If `iso_year` is True, return bounds for ISO-8601 week-numbering years.
    """
    if iso_year:
        first = datetime.datetime.fromisocalendar(value, 1, 1)
        second = datetime.datetime.fromisocalendar(
            value + 1, 1, 1
        ) - datetime.timedelta(microseconds=1)
    else:
        first = datetime.datetime(value, 1, 1)
        second = datetime.datetime(value, 12, 31, 23, 59, 59, 999999)

    # Make sure that datetimes are aware in the current timezone
    tz = timezone.get_current_timezone()
    first = timezone.make_aware(first, tz)
    second = timezone.make_aware(second, tz)
    return [first, second]


def combine_expression(connector: str, sub_expressions: list[str]) -> str:
    """
    Combine a list of subexpressions into a single expression, using
    the provided connecting operator.
    """
    conn = f" {connector} "
    return conn.join(sub_expressions)


def subtract_temporals(
    internal_type: str,
    lhs: tuple[str, list[Any] | tuple[Any, ...]],
    rhs: tuple[str, list[Any] | tuple[Any, ...]],
) -> tuple[str, tuple[Any, ...]]:
    lhs_sql, lhs_params = lhs
    rhs_sql, rhs_params = rhs
    params = (*lhs_params, *rhs_params)
    if internal_type == "DateField":
        return f"(interval '1 day' * ({lhs_sql} - {rhs_sql}))", params
    # Use native temporal subtraction
    return f"({lhs_sql} - {rhs_sql})", params


def window_frame_start(start: int | None) -> str:
    if isinstance(start, int):
        if start < 0:
            return "%d %s" % (abs(start), PRECEDING)  # noqa: UP031
        elif start == 0:
            return CURRENT_ROW
    elif start is None:
        return UNBOUNDED_PRECEDING
    raise ValueError(
        f"start argument must be a negative integer, zero, or None, but got '{start}'."
    )


def window_frame_end(end: int | None) -> str:
    if isinstance(end, int):
        if end == 0:
            return CURRENT_ROW
        elif end > 0:
            return "%d %s" % (end, FOLLOWING)  # noqa: UP031
    elif end is None:
        return UNBOUNDED_FOLLOWING
    raise ValueError(
        f"end argument must be a positive integer, zero, or None, but got '{end}'."
    )


def window_frame_rows_start_end(
    start: int | None = None, end: int | None = None
) -> tuple[str, str]:
    """Return SQL for start and end points in an OVER clause window frame."""
    return window_frame_start(start), window_frame_end(end)


def window_frame_range_start_end(
    start: int | None = None, end: int | None = None
) -> tuple[str, str]:
    start_, end_ = window_frame_rows_start_end(start, end)
    # PostgreSQL only supports UNBOUNDED with PRECEDING/FOLLOWING
    if (start and start < 0) or (end and end > 0):
        raise NotSupportedError(
            "PostgreSQL only supports UNBOUNDED together with PRECEDING and FOLLOWING."
        )
    return start_, end_


def explain_query_prefix(format: str | None = None, **options: Any) -> str:
    extra = {}
    # Normalize options.
    if options:
        options = {
            name.upper(): "true" if value else "false"
            for name, value in options.items()
        }
        for valid_option in EXPLAIN_OPTIONS:
            value = options.pop(valid_option, None)
            if value is not None:
                extra[valid_option] = value
    if format:
        normalized_format = format.upper()
        if normalized_format not in SUPPORTED_EXPLAIN_FORMATS:
            msg = "{} is not a recognized format. Allowed formats: {}".format(
                normalized_format, ", ".join(sorted(SUPPORTED_EXPLAIN_FORMATS))
            )
            raise ValueError(msg)
        extra["FORMAT"] = format
    if options:
        raise ValueError(
            "Unknown options: {}".format(", ".join(sorted(options.keys())))
        )
    prefix = EXPLAIN_PREFIX
    if extra:
        prefix += " ({})".format(", ".join("{} {}".format(*i) for i in extra.items()))
    return prefix


def on_conflict_suffix_sql(
    fields: list[Field],
    on_conflict: OnConflict | None,
    update_fields: Iterable[str],
    unique_fields: Iterable[str],
) -> str:
    if on_conflict == OnConflict.IGNORE:
        return "ON CONFLICT DO NOTHING"
    if on_conflict == OnConflict.UPDATE:
        return "ON CONFLICT({}) DO UPDATE SET {}".format(
            ", ".join(map(quote_name, unique_fields)),
            ", ".join(
                [
                    f"{field} = EXCLUDED.{field}"
                    for field in map(quote_name, update_fields)
                ]
            ),
        )
    return ""
