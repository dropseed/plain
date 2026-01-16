from __future__ import annotations

import datetime
import ipaddress
import json
from collections.abc import Callable, Iterable
from functools import cached_property, lru_cache, partial
from typing import TYPE_CHECKING, Any, LiteralString, cast

from psycopg import ClientCursor, errors, sql
from psycopg.types import numeric
from psycopg.types.json import Jsonb

from plain.models.backends.utils import CursorWrapper, split_tzname_delta
from plain.models.constants import OnConflict
from plain.models.db import NotSupportedError
from plain.models.expressions import ResolvableExpression
from plain.utils import timezone
from plain.utils.regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from plain.models.backends.wrapper import DatabaseWrapper
    from plain.models.fields import Field
    from plain.models.sql.compiler import SQLCompiler
    from plain.models.sql.query import Query


@lru_cache
def get_json_dumps(
    encoder: type[json.JSONEncoder] | None,
) -> Callable[..., str]:
    if encoder is None:
        return json.dumps
    return partial(json.dumps, cls=encoder)


class DatabaseOperations:
    """
    PostgreSQL-specific SQL generation and type handling.

    Encapsulates PostgreSQL-specific differences, such as the way it performs
    ordering or calculates the ID of a recently-inserted row.
    """

    # Integer field safe ranges by `internal_type` as documented
    # in docs/ref/models/fields.txt.
    integer_field_ranges: dict[str, tuple[int, int]] = {
        "SmallIntegerField": (-32768, 32767),
        "IntegerField": (-2147483648, 2147483647),
        "BigIntegerField": (-9223372036854775808, 9223372036854775807),
        "PositiveBigIntegerField": (0, 9223372036854775807),
        "PositiveSmallIntegerField": (0, 32767),
        "PositiveIntegerField": (0, 2147483647),
        "PrimaryKeyField": (-9223372036854775808, 9223372036854775807),
    }
    # Mapping of Field.get_internal_type() (typically the model field's class
    # name) to the data type to use for the Cast() function, if different from
    # DatabaseWrapper.data_types.
    cast_data_types: dict[str, str] = {
        "PrimaryKeyField": "bigint",
    }
    # CharField data type if the max_length argument isn't provided.
    cast_char_field_without_max_length: str | None = "varchar"

    # Start and end points for window expressions.
    PRECEDING: str = "PRECEDING"
    FOLLOWING: str = "FOLLOWING"
    UNBOUNDED_PRECEDING: str = "UNBOUNDED " + PRECEDING
    UNBOUNDED_FOLLOWING: str = "UNBOUNDED " + FOLLOWING
    CURRENT_ROW: str = "CURRENT ROW"

    # Prefix for EXPLAIN queries
    explain_prefix: str = "EXPLAIN"
    explain_options = frozenset(
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
    # PostgreSQL EXPLAIN output formats
    supported_explain_formats: set[str] = {"JSON", "TEXT", "XML", "YAML"}

    # PostgreSQL integer type mapping for psycopg
    integerfield_type_map = {
        "SmallIntegerField": numeric.Int2,
        "IntegerField": numeric.Int4,
        "BigIntegerField": numeric.Int8,
        "PositiveSmallIntegerField": numeric.Int2,
        "PositiveIntegerField": numeric.Int4,
        "PositiveBigIntegerField": numeric.Int8,
    }

    # Maximum length of an identifier (63 by default in PostgreSQL).
    # Can be changed by recompiling PostgreSQL after editing the NAMEDATALEN
    # macro in src/include/pg_config_manual.h.
    MAX_NAME_LENGTH: int = 63

    # Value to use during INSERT to specify that a field should use its default value.
    PK_DEFAULT_VALUE: str = "DEFAULT"

    # SQL clause to make a constraint "initially deferred" during CREATE TABLE.
    DEFERRABLE_SQL: str = " DEFERRABLE INITIALLY DEFERRED"

    # EXTRACT format cannot be passed in parameters.
    _extract_format_re = _lazy_re_compile(r"[A-Z_]+")

    def __init__(self, connection: DatabaseWrapper):
        self.connection = connection

    def unification_cast_sql(self, output_field: Field) -> str:
        """
        Given a field instance, return the SQL that casts the result of a union
        to that type. The resulting string should contain a '%s' placeholder
        for the expression being cast.
        """
        internal_type = output_field.get_internal_type()
        if internal_type in (
            "GenericIPAddressField",
            "TimeField",
            "UUIDField",
        ):
            # PostgreSQL will resolve a union as type 'text' if input types are
            # 'unknown'.
            # https://www.postgresql.org/docs/current/typeconv-union-case.html
            # These fields cannot be implicitly cast back in the default
            # PostgreSQL configuration so we need to explicitly cast them.
            # We must also remove components of the type within brackets:
            # varchar(255) -> varchar.
            db_type = output_field.db_type(self.connection)
            if db_type:
                return "CAST(%s AS {})".format(db_type.split("(")[0])
        return "%s"

    def date_extract_sql(
        self, lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
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
        if not self._extract_format_re.fullmatch(lookup_type):
            raise ValueError(f"Invalid lookup type: {lookup_type!r}")
        return f"EXTRACT({lookup_type} FROM {sql})", params

    def date_trunc_sql(
        self,
        lookup_type: str,
        sql: str,
        params: list[Any] | tuple[Any, ...],
        tzname: str | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        """
        Given a lookup_type of 'year', 'month', or 'day', return the SQL that
        truncates the given date or datetime field field_name to a date object
        with only the given specificity.

        If `tzname` is provided, the given value is truncated in a specific
        timezone.
        """
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-TRUNC
        return f"DATE_TRUNC(%s, {sql})", (lookup_type, *params)

    def _prepare_tzname_delta(self, tzname: str) -> str:
        tzname, sign, offset = split_tzname_delta(tzname)
        if offset:
            sign = "-" if sign == "+" else "+"
            return f"{tzname}{sign}{offset}"
        return tzname

    def _convert_sql_to_tz(
        self, sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        if tzname:
            tzname_param = self._prepare_tzname_delta(tzname)
            return f"{sql} AT TIME ZONE %s", (*params, tzname_param)
        return sql, params

    def datetime_cast_date_sql(
        self, sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Return the SQL to cast a datetime value to date value.
        """
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        return f"({sql})::date", params

    def datetime_cast_time_sql(
        self, sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Return the SQL to cast a datetime value to time value.
        """
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        return f"({sql})::time", params

    def datetime_extract_sql(
        self,
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
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        if lookup_type == "second":
            # Truncate fractional seconds.
            return f"EXTRACT(SECOND FROM DATE_TRUNC(%s, {sql}))", ("second", *params)
        return self.date_extract_sql(lookup_type, sql, params)

    def datetime_trunc_sql(
        self,
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
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-TRUNC
        return f"DATE_TRUNC(%s, {sql})", (lookup_type, *params)

    def time_extract_sql(
        self, lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Given a lookup_type of 'hour', 'minute', or 'second', return the SQL
        that extracts a value from the given time field field_name.
        """
        if lookup_type == "second":
            # Truncate fractional seconds.
            return f"EXTRACT(SECOND FROM DATE_TRUNC(%s, {sql}))", ("second", *params)
        return self.date_extract_sql(lookup_type, sql, params)

    def time_trunc_sql(
        self,
        lookup_type: str,
        sql: str,
        params: list[Any] | tuple[Any, ...],
        tzname: str | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        """
        Given a lookup_type of 'hour', 'minute' or 'second', return the SQL
        that truncates the given time or datetime field field_name to a time
        object with only the given specificity.

        If `tzname` is provided, the given value is truncated in a specific
        timezone.
        """
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        return f"DATE_TRUNC(%s, {sql})::time", (lookup_type, *params)

    def distinct_sql(
        self, fields: list[str], params: list[Any] | tuple[Any, ...]
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

    def fetch_returned_insert_columns(
        self, cursor: CursorWrapper, returning_params: Any
    ) -> Any:
        """
        Given a cursor object that has just performed an INSERT...RETURNING
        statement into a table, return the newly created data.
        """
        return cursor.fetchone()

    def for_update_sql(
        self,
        nowait: bool = False,
        skip_locked: bool = False,
        of: tuple[str, ...] = (),
        no_key: bool = False,
    ) -> str:
        """
        Return the FOR UPDATE SQL clause to lock rows for an update operation.
        """
        return "FOR{} UPDATE{}{}{}".format(
            " NO KEY" if no_key else "",
            " OF {}".format(", ".join(of)) if of else "",
            " NOWAIT" if nowait else "",
            " SKIP LOCKED" if skip_locked else "",
        )

    def _get_limit_offset_params(
        self, low_mark: int | None, high_mark: int | None
    ) -> tuple[int | None, int]:
        offset = low_mark or 0
        if high_mark is not None:
            return (high_mark - offset), offset
        elif offset:
            return None, offset  # PostgreSQL allows omitting LIMIT clause
        return None, offset

    def limit_offset_sql(self, low_mark: int | None, high_mark: int | None) -> str:
        """Return LIMIT/OFFSET SQL clause."""
        limit, offset = self._get_limit_offset_params(low_mark, high_mark)
        return " ".join(
            sql
            for sql in (
                ("LIMIT %d" % limit) if limit else None,  # noqa: UP031
                ("OFFSET %d" % offset) if offset else None,  # noqa: UP031
            )
            if sql
        )

    def last_executed_query(
        self,
        cursor: CursorWrapper,
        sql: str,
        params: Any,
    ) -> str | None:
        """
        Return a string of the query last executed by the given cursor, with
        placeholders replaced with actual values.

        `sql` is the raw query containing placeholders and `params` is the
        sequence of parameters.
        """
        try:
            return self.compose_sql(sql, params)
        except errors.DataError:
            return None

    def last_insert_id(
        self, cursor: CursorWrapper, table_name: str, pk_name: str
    ) -> int:
        """
        Given a cursor object that has just performed an INSERT statement into
        a table that has an auto-incrementing ID, return the newly created ID.

        `pk_name` is the name of the primary-key column.
        """
        return cursor.lastrowid

    def lookup_cast(self, lookup_type: str, internal_type: str | None = None) -> str:
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

    def return_insert_columns(self, fields: list[Field]) -> tuple[str, tuple[Any, ...]]:
        """
        Return the RETURNING clause SQL and params to append to an INSERT query.
        """
        if not fields:
            return "", ()
        columns = [
            f"{self.quote_name(field.model.model_options.db_table)}.{self.quote_name(field.column)}"
            for field in fields
        ]
        return "RETURNING {}".format(", ".join(columns)), ()

    def bulk_insert_sql(
        self, fields: list[Field], placeholder_rows: list[list[str]]
    ) -> str:
        """
        Return the SQL for bulk inserting rows.
        """
        placeholder_rows_sql = (", ".join(row) for row in placeholder_rows)
        values_sql = ", ".join(f"({sql})" for sql in placeholder_rows_sql)
        return "VALUES " + values_sql

    def fetch_returned_insert_rows(self, cursor: CursorWrapper) -> list[Any]:
        """
        Given a cursor object that has just performed an INSERT...RETURNING
        statement into a table, return the list of returned data.
        """
        return cursor.fetchall()

    @cached_property
    def compilers(self) -> dict[type[Query], type[SQLCompiler]]:
        """Return a mapping of Query types to their SQLCompiler implementations."""
        from plain.models.sql.compiler import (
            SQLAggregateCompiler,
            SQLCompiler,
            SQLDeleteCompiler,
            SQLInsertCompiler,
            SQLUpdateCompiler,
        )
        from plain.models.sql.query import Query
        from plain.models.sql.subqueries import (
            AggregateQuery,
            DeleteQuery,
            InsertQuery,
            UpdateQuery,
        )

        return {
            Query: SQLCompiler,
            DeleteQuery: SQLDeleteCompiler,
            UpdateQuery: SQLUpdateCompiler,
            InsertQuery: SQLInsertCompiler,
            AggregateQuery: SQLAggregateCompiler,
        }

    def get_compiler_for(self, query: Query, elide_empty: bool = True) -> SQLCompiler:
        """
        Return a compiler instance for the given query.
        Walks the query's MRO to find the appropriate compiler class.
        """
        for query_cls in type(query).__mro__:
            if query_cls in self.compilers:
                return self.compilers[query_cls](query, self.connection, elide_empty)
        raise TypeError(f"No compiler registered for {type(query)}")

    def quote_name(self, name: str) -> str:
        """
        Return a quoted version of the given table, index, or column name. Do
        not quote the given name if it's already been quoted.
        """
        if name.startswith('"') and name.endswith('"'):
            return name  # Quoting once is enough.
        return f'"{name}"'

    def compose_sql(self, query: str, params: Any) -> str:
        assert self.connection.connection is not None
        return ClientCursor(self.connection.connection).mogrify(
            sql.SQL(cast(LiteralString, query)), params
        )

    def regex_lookup(self, lookup_type: str) -> str:
        """
        Return the string to use in a query when performing regular expression
        lookups (using "regex" or "iregex"). It should contain a '%s'
        placeholder for the column being searched against.
        """
        # PostgreSQL uses ~ for regex and ~* for case-insensitive regex
        if lookup_type == "regex":
            return "%s ~ %s"
        return "%s ~* %s"

    def savepoint_create_sql(self, sid: str) -> str:
        """
        Return the SQL for starting a new savepoint. Only required if the
        "uses_savepoints" feature is True. The "sid" parameter is a string
        for the savepoint id.
        """
        return f"SAVEPOINT {self.quote_name(sid)}"

    def savepoint_commit_sql(self, sid: str) -> str:
        """
        Return the SQL for committing the given savepoint.
        """
        return f"RELEASE SAVEPOINT {self.quote_name(sid)}"

    def savepoint_rollback_sql(self, sid: str) -> str:
        """
        Return the SQL for rolling back the given savepoint.
        """
        return f"ROLLBACK TO SAVEPOINT {self.quote_name(sid)}"

    def set_time_zone_sql(self) -> str:
        """
        Return the SQL that will set the connection's time zone.
        """
        return "SELECT set_config('TimeZone', %s, false)"

    def prep_for_like_query(self, x: str) -> str:
        """Prepare a value for use in a LIKE query."""
        return str(x).replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

    def prep_for_iexact_query(self, x: str) -> str:
        return x

    def adapt_unknown_value(self, value: Any) -> Any:
        """
        Transform a value to something compatible with the backend driver.

        This method only depends on the type of the value. It's designed for
        cases where the target type isn't known, such as .raw() SQL queries.
        As a consequence it may not work perfectly in all circumstances.

        PostgreSQL's psycopg driver handles datetime, date, time, and decimal
        types natively, so no adaptation is needed.
        """
        return value

    def adapt_integerfield_value(
        self, value: int | Any | None, internal_type: str
    ) -> int | Any | None:
        if value is None or isinstance(value, ResolvableExpression):
            return value
        return self.integerfield_type_map[internal_type](value)

    def adapt_ipaddressfield_value(
        self, value: str | None
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        """
        Transform a string representation of an IP address into the expected
        type for the backend driver.
        """
        if value:
            return ipaddress.ip_address(value)
        return None

    def adapt_json_value(
        self, value: Any, encoder: type[json.JSONEncoder] | None
    ) -> Jsonb:
        return Jsonb(value, dumps=get_json_dumps(encoder))

    def year_lookup_bounds_for_date_field(
        self, value: int, iso_year: bool = False
    ) -> list[datetime.date]:
        """
        Return a two-elements list with the lower and upper bound to be used
        with a BETWEEN operator to query a DateField value using a year
        lookup.

        `value` is an int, containing the looked-up year.
        If `iso_year` is True, return bounds for ISO-8601 week-numbering years.
        """
        if iso_year:
            first = datetime.date.fromisocalendar(value, 1, 1)
            second = datetime.date.fromisocalendar(
                value + 1, 1, 1
            ) - datetime.timedelta(days=1)
        else:
            first = datetime.date(value, 1, 1)
            second = datetime.date(value, 12, 31)
        return [first, second]

    def year_lookup_bounds_for_datetime_field(
        self, value: int, iso_year: bool = False
    ) -> list[datetime.datetime]:
        """
        Return a two-elements list with the lower and upper bound to be used
        with a BETWEEN operator to query a DateTimeField value using a year
        lookup.

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

    def convert_durationfield_value(
        self, value: int | None, expression: Any, connection: DatabaseWrapper
    ) -> datetime.timedelta | None:
        if value is not None:
            return datetime.timedelta(0, 0, value)
        return None

    def combine_expression(self, connector: str, sub_expressions: list[str]) -> str:
        """
        Combine a list of subexpressions into a single expression, using
        the provided connecting operator.
        """
        conn = f" {connector} "
        return conn.join(sub_expressions)

    def integer_field_range(self, internal_type: str) -> tuple[int, int]:
        """
        Given an integer field internal type (e.g. 'PositiveIntegerField'),
        return a tuple of the (min_value, max_value) form representing the
        range of the column type bound to the field.
        """
        return self.integer_field_ranges[internal_type]

    def subtract_temporals(
        self,
        internal_type: str,
        lhs: tuple[str, list[Any] | tuple[Any, ...]],
        rhs: tuple[str, list[Any] | tuple[Any, ...]],
    ) -> tuple[str, tuple[Any, ...]]:
        lhs_sql, lhs_params = lhs
        rhs_sql, rhs_params = rhs
        params = (*lhs_params, *rhs_params)
        if internal_type == "DateField":
            return f"(interval '1 day' * ({lhs_sql} - {rhs_sql}))", params
        # PostgreSQL supports temporal subtraction natively
        return f"({lhs_sql} - {rhs_sql})", params

    def window_frame_start(self, start: int | None) -> str:
        if isinstance(start, int):
            if start < 0:
                return "%d %s" % (abs(start), self.PRECEDING)  # noqa: UP031
            elif start == 0:
                return self.CURRENT_ROW
        elif start is None:
            return self.UNBOUNDED_PRECEDING
        raise ValueError(
            f"start argument must be a negative integer, zero, or None, but got '{start}'."
        )

    def window_frame_end(self, end: int | None) -> str:
        if isinstance(end, int):
            if end == 0:
                return self.CURRENT_ROW
            elif end > 0:
                return "%d %s" % (end, self.FOLLOWING)  # noqa: UP031
        elif end is None:
            return self.UNBOUNDED_FOLLOWING
        raise ValueError(
            f"end argument must be a positive integer, zero, or None, but got '{end}'."
        )

    def window_frame_rows_start_end(
        self, start: int | None = None, end: int | None = None
    ) -> tuple[str, str]:
        """
        Return SQL for start and end points in an OVER clause window frame.
        """
        # PostgreSQL supports window functions
        return self.window_frame_start(start), self.window_frame_end(end)

    def window_frame_range_start_end(
        self, start: int | None = None, end: int | None = None
    ) -> tuple[str, str]:
        start_, end_ = self.window_frame_rows_start_end(start, end)
        # PostgreSQL only supports UNBOUNDED with PRECEDING/FOLLOWING
        if (start and start < 0) or (end and end > 0):
            raise NotSupportedError(
                "PostgreSQL only supports UNBOUNDED together with PRECEDING and "
                "FOLLOWING."
            )
        return start_, end_

    def explain_query_prefix(self, format: str | None = None, **options: Any) -> str:
        extra = {}
        # Normalize options.
        if options:
            options = {
                name.upper(): "true" if value else "false"
                for name, value in options.items()
            }
            for valid_option in self.explain_options:
                value = options.pop(valid_option, None)
                if value is not None:
                    extra[valid_option] = value
        if format:
            normalized_format = format.upper()
            if normalized_format not in self.supported_explain_formats:
                msg = "{} is not a recognized format. Allowed formats: {}".format(
                    normalized_format, ", ".join(sorted(self.supported_explain_formats))
                )
                raise ValueError(msg)
            extra["FORMAT"] = format
        if options:
            raise ValueError(
                "Unknown options: {}".format(", ".join(sorted(options.keys())))
            )
        prefix = self.explain_prefix
        if extra:
            prefix += " ({})".format(
                ", ".join("{} {}".format(*i) for i in extra.items())
            )
        return prefix

    def insert_statement(self, on_conflict: Any = None) -> str:
        return "INSERT INTO"

    def on_conflict_suffix_sql(
        self,
        fields: list[Field],
        on_conflict: OnConflict | None,
        update_fields: Iterable[str],
        unique_fields: Iterable[str],
    ) -> str:
        if on_conflict == OnConflict.IGNORE:
            return "ON CONFLICT DO NOTHING"
        if on_conflict == OnConflict.UPDATE:
            return "ON CONFLICT({}) DO UPDATE SET {}".format(
                ", ".join(map(self.quote_name, unique_fields)),
                ", ".join(
                    [
                        f"{field} = EXCLUDED.{field}"
                        for field in map(self.quote_name, update_fields)
                    ]
                ),
            )
        return ""
