from __future__ import annotations

import datetime
import decimal
import json
from importlib import import_module
from typing import TYPE_CHECKING, Any

import sqlparse

from plain.models.backends import utils
from plain.models.db import NotSupportedError
from plain.utils import timezone
from plain.utils.encoding import force_str

if TYPE_CHECKING:
    from types import ModuleType

    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.fields import Field


class BaseDatabaseOperations:
    """
    Encapsulate backend-specific differences, such as the way a backend
    performs ordering or calculates the ID of a recently-inserted row.
    """

    compiler_module: str = "plain.models.sql.compiler"

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
    set_operators: dict[str, str] = {
        "union": "UNION",
        "intersection": "INTERSECT",
        "difference": "EXCEPT",
    }
    # Mapping of Field.get_internal_type() (typically the model field's class
    # name) to the data type to use for the Cast() function, if different from
    # DatabaseWrapper.data_types.
    cast_data_types: dict[str, str] = {}
    # CharField data type if the max_length argument isn't provided.
    cast_char_field_without_max_length: str | None = None

    # Start and end points for window expressions.
    PRECEDING: str = "PRECEDING"
    FOLLOWING: str = "FOLLOWING"
    UNBOUNDED_PRECEDING: str = "UNBOUNDED " + PRECEDING
    UNBOUNDED_FOLLOWING: str = "UNBOUNDED " + FOLLOWING
    CURRENT_ROW: str = "CURRENT ROW"

    # Prefix for EXPLAIN queries, or None EXPLAIN isn't supported.
    explain_prefix: str | None = None

    def __init__(self, connection: BaseDatabaseWrapper):
        self.connection = connection
        self._cache: ModuleType | None = None

    def autoinc_sql(self, table: str, column: str) -> str | None:
        """
        Return any SQL needed to support auto-incrementing primary keys, or
        None if no SQL is necessary.

        This SQL is executed when a table is created.
        """
        return None

    def bulk_batch_size(self, fields: list[Field], objs: list[Any]) -> int:
        """
        Return the maximum allowed batch size for the backend. The fields
        are the fields going to be inserted in the batch, the objs contains
        all the objects to be inserted.
        """
        return len(objs)

    def format_for_duration_arithmetic(self, sql: str) -> str:
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a "
            "format_for_duration_arithmetic() method."
        )

    def unification_cast_sql(self, output_field: Field) -> str:
        """
        Given a field instance, return the SQL that casts the result of a union
        to that type. The resulting string should contain a '%s' placeholder
        for the expression being cast.
        """
        return "%s"

    def date_extract_sql(
        self, lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Given a lookup_type of 'year', 'month', or 'day', return the SQL that
        extracts a value from the given date field field_name.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a date_extract_sql() "
            "method"
        )

    def date_trunc_sql(
        self,
        lookup_type: str,
        sql: str,
        params: list[Any] | tuple[Any, ...],
        tzname: str | None = None,
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Given a lookup_type of 'year', 'month', or 'day', return the SQL that
        truncates the given date or datetime field field_name to a date object
        with only the given specificity.

        If `tzname` is provided, the given value is truncated in a specific
        timezone.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a date_trunc_sql() "
            "method."
        )

    def datetime_cast_date_sql(
        self, sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Return the SQL to cast a datetime value to date value.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a "
            "datetime_cast_date_sql() method."
        )

    def datetime_cast_time_sql(
        self, sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Return the SQL to cast a datetime value to time value.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a "
            "datetime_cast_time_sql() method"
        )

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
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a datetime_extract_sql() "
            "method"
        )

    def datetime_trunc_sql(
        self,
        lookup_type: str,
        sql: str,
        params: list[Any] | tuple[Any, ...],
        tzname: str | None,
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Given a lookup_type of 'year', 'month', 'day', 'hour', 'minute', or
        'second', return the SQL that truncates the given datetime field
        field_name to a datetime object with only the given specificity.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a datetime_trunc_sql() "
            "method"
        )

    def time_trunc_sql(
        self,
        lookup_type: str,
        sql: str,
        params: list[Any] | tuple[Any, ...],
        tzname: str | None = None,
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Given a lookup_type of 'hour', 'minute' or 'second', return the SQL
        that truncates the given time or datetime field field_name to a time
        object with only the given specificity.

        If `tzname` is provided, the given value is truncated in a specific
        timezone.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a time_trunc_sql() method"
        )

    def time_extract_sql(
        self, lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        """
        Given a lookup_type of 'hour', 'minute', or 'second', return the SQL
        that extracts a value from the given time field field_name.
        """
        return self.date_extract_sql(lookup_type, sql, params)

    def deferrable_sql(self) -> str:
        """
        Return the SQL to make a constraint "initially deferred" during a
        CREATE TABLE statement.
        """
        return ""

    def distinct_sql(
        self, fields: list[str], params: list[Any] | tuple[Any, ...]
    ) -> tuple[list[str], list[Any]]:
        """
        Return an SQL DISTINCT clause which removes duplicate rows from the
        result set. If any fields are given, only check the given fields for
        duplicates.
        """
        if fields:
            raise NotSupportedError(
                "DISTINCT ON fields is not supported by this database backend"
            )
        else:
            return ["DISTINCT"], []

    def fetch_returned_insert_columns(self, cursor: Any, returning_params: Any) -> Any:
        """
        Given a cursor object that has just performed an INSERT...RETURNING
        statement into a table, return the newly created data.
        """
        return cursor.fetchone()

    def field_cast_sql(self, db_type: str | None, internal_type: str) -> str:
        """
        Given a column type (e.g. 'BLOB', 'VARCHAR') and an internal type
        (e.g. 'GenericIPAddressField'), return the SQL to cast it before using
        it in a WHERE statement. The resulting string should contain a '%s'
        placeholder for the column being searched against.
        """
        return "%s"

    def force_no_ordering(self) -> list[str]:
        """
        Return a list used in the "ORDER BY" clause to force no ordering at
        all. Return an empty list to include nothing in the ordering.
        """
        return []

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
            return self.connection.ops.no_limit_value(), offset
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
        cursor: Any,
        sql: str,
        params: list[Any] | tuple[Any, ...] | dict[str, Any] | None,
    ) -> str:
        """
        Return a string of the query last executed by the given cursor, with
        placeholders replaced with actual values.

        `sql` is the raw query containing placeholders and `params` is the
        sequence of parameters. These are used by default, but this method
        exists for database backends to provide a better implementation
        according to their own quoting schemes.
        """

        # Convert params to contain string values.
        def to_string(s: Any) -> str:
            return force_str(s, strings_only=True, errors="replace")

        u_params: tuple[str, ...] | dict[str, str]
        if isinstance(params, (list, tuple)):  # noqa: UP038
            u_params = tuple(to_string(val) for val in params)
        elif params is None:
            u_params = ()
        else:
            u_params = {to_string(k): to_string(v) for k, v in params.items()}  # type: ignore[union-attr]

        return f"QUERY = {sql!r} - PARAMS = {u_params!r}"

    def last_insert_id(self, cursor: Any, table_name: str, pk_name: str) -> int:
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
        return "%s"

    def max_in_list_size(self) -> int | None:
        """
        Return the maximum number of items that can be passed in a single 'IN'
        list condition, or None if the backend does not impose a limit.
        """
        return None

    def max_name_length(self) -> int | None:
        """
        Return the maximum length of table and column names, or None if there
        is no limit.
        """
        return None

    def no_limit_value(self) -> int | None:
        """
        Return the value to use for the LIMIT when we are wanting "LIMIT
        infinity". Return None if the limit clause can be omitted in this case.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a no_limit_value() method"
        )

    def pk_default_value(self) -> str:
        """
        Return the value to use during an INSERT statement to specify that
        the field should use its default value.
        """
        return "DEFAULT"

    def prepare_sql_script(self, sql: str) -> list[str]:
        """
        Take an SQL script that may contain multiple lines and return a list
        of statements to feed to successive cursor.execute() calls.

        Since few databases are able to process raw SQL scripts in a single
        cursor.execute() call and PEP 249 doesn't talk about this use case,
        the default implementation is conservative.
        """
        return [
            sqlparse.format(statement, strip_comments=True)
            for statement in sqlparse.split(sql)
            if statement
        ]

    def return_insert_columns(
        self, fields: list[Field]
    ) -> tuple[str, list[Any]] | None:
        """
        For backends that support returning columns as part of an insert query,
        return the SQL and params to append to the INSERT query. The returned
        fragment should contain a format string to hold the appropriate column.
        """
        return None

    def compiler(self, compiler_name: str) -> type[Any]:
        """
        Return the SQLCompiler class corresponding to the given name,
        in the namespace corresponding to the `compiler_module` attribute
        on this backend.
        """
        if self._cache is None:
            self._cache = import_module(self.compiler_module)
        return getattr(self._cache, compiler_name)

    def quote_name(self, name: str) -> str:
        """
        Return a quoted version of the given table, index, or column name. Do
        not quote the given name if it's already been quoted.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a quote_name() method"
        )

    def regex_lookup(self, lookup_type: str) -> str:
        """
        Return the string to use in a query when performing regular expression
        lookups (using "regex" or "iregex"). It should contain a '%s'
        placeholder for the column being searched against.

        If the feature is not supported (or part of it is not supported), raise
        NotImplementedError.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseOperations may require a regex_lookup() method"
        )

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

        Return '' if the backend doesn't support time zones.
        """
        return ""

    def prep_for_like_query(self, x: str) -> str:
        """Prepare a value for use in a LIKE query."""
        return str(x).replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

    # Same as prep_for_like_query(), but called for "iexact" matches, which
    # need not necessarily be implemented using "LIKE" in the backend.
    prep_for_iexact_query = prep_for_like_query

    def validate_autopk_value(self, value: int) -> int:
        """
        Certain backends do not accept some values for "serial" fields
        (for example zero in MySQL). Raise a ValueError if the value is
        invalid, otherwise return the validated value.
        """
        return value

    def adapt_unknown_value(self, value: Any) -> Any:
        """
        Transform a value to something compatible with the backend driver.

        This method only depends on the type of the value. It's designed for
        cases where the target type isn't known, such as .raw() SQL queries.
        As a consequence it may not work perfectly in all circumstances.
        """
        if isinstance(value, datetime.datetime):  # must be before date
            return self.adapt_datetimefield_value(value)
        elif isinstance(value, datetime.date):
            return self.adapt_datefield_value(value)
        elif isinstance(value, datetime.time):
            return self.adapt_timefield_value(value)
        elif isinstance(value, decimal.Decimal):
            return self.adapt_decimalfield_value(value)
        else:
            return value

    def adapt_integerfield_value(
        self, value: int | None, internal_type: str
    ) -> int | None:
        return value

    def adapt_datefield_value(self, value: datetime.date | None) -> str | None:
        """
        Transform a date value to an object compatible with what is expected
        by the backend driver for date columns.
        """
        if value is None:
            return None
        return str(value)

    def adapt_datetimefield_value(
        self, value: datetime.datetime | Any | None
    ) -> str | Any | None:
        """
        Transform a datetime value to an object compatible with what is expected
        by the backend driver for datetime columns.
        """
        if value is None:
            return None
        # Expression values are adapted by the database.
        if hasattr(value, "resolve_expression"):
            return value

        return str(value)

    def adapt_timefield_value(
        self, value: datetime.time | Any | None
    ) -> str | Any | None:
        """
        Transform a time value to an object compatible with what is expected
        by the backend driver for time columns.
        """
        if value is None:
            return None
        # Expression values are adapted by the database.
        if hasattr(value, "resolve_expression"):
            return value

        if timezone.is_aware(value):  # type: ignore[arg-type]
            raise ValueError("Plain does not support timezone-aware times.")
        return str(value)

    def adapt_decimalfield_value(
        self,
        value: decimal.Decimal | None,
        max_digits: int | None = None,
        decimal_places: int | None = None,
    ) -> str | None:
        """
        Transform a decimal.Decimal value to an object compatible with what is
        expected by the backend driver for decimal (numeric) columns.
        """
        return utils.format_number(value, max_digits, decimal_places)

    def adapt_ipaddressfield_value(self, value: str | None) -> str | None:
        """
        Transform a string representation of an IP address into the expected
        type for the backend driver.
        """
        return value or None

    def adapt_json_value(self, value: Any, encoder: type[json.JSONEncoder]) -> str:
        return json.dumps(value, cls=encoder)

    def year_lookup_bounds_for_date_field(
        self, value: int, iso_year: bool = False
    ) -> list[str | None]:
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
        first_adapted = self.adapt_datefield_value(first)
        second_adapted = self.adapt_datefield_value(second)
        return [first_adapted, second_adapted]

    def year_lookup_bounds_for_datetime_field(
        self, value: int, iso_year: bool = False
    ) -> list[str | Any | None]:
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

        first_adapted = self.adapt_datetimefield_value(first)
        second_adapted = self.adapt_datetimefield_value(second)
        return [first_adapted, second_adapted]

    def get_db_converters(self, expression: Any) -> list[Any]:
        """
        Return a list of functions needed to convert field data.

        Some field types on some backends do not provide data in the correct
        format, this is the hook for converter functions.
        """
        return []

    def convert_durationfield_value(
        self, value: int | None, expression: Any, connection: BaseDatabaseWrapper
    ) -> datetime.timedelta | None:
        if value is not None:
            return datetime.timedelta(0, 0, value)
        return None

    def check_expression_support(self, expression: Any) -> None:
        """
        Check that the backend supports the provided expression.

        This is used on specific backends to rule out known expressions
        that have problematic or nonexistent implementations. If the
        expression has a known problem, the backend should raise
        NotSupportedError.
        """
        return None

    def conditional_expression_supported_in_where_clause(self, expression: Any) -> bool:
        """
        Return True, if the conditional expression is supported in the WHERE
        clause.
        """
        return True

    def combine_expression(self, connector: str, sub_expressions: list[str]) -> str:
        """
        Combine a list of subexpressions into a single expression, using
        the provided connecting operator. This is required because operators
        can vary between backends (e.g., Oracle with %% and &) and between
        subexpression types (e.g., date expressions).
        """
        conn = f" {connector} "
        return conn.join(sub_expressions)

    def combine_duration_expression(
        self, connector: str, sub_expressions: list[str]
    ) -> str:
        return self.combine_expression(connector, sub_expressions)

    def binary_placeholder_sql(self, value: Any) -> str:
        """
        Some backends require special syntax to insert binary content (MySQL
        for example uses '_binary %s').
        """
        return "%s"

    def modify_insert_params(
        self, placeholder: str, params: list[Any] | tuple[Any, ...]
    ) -> list[Any] | tuple[Any, ...]:
        """
        Allow modification of insert parameters. Needed for Oracle Spatial
        backend due to #10888.
        """
        return params

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
        if self.connection.features.supports_temporal_subtraction:
            lhs_sql, lhs_params = lhs
            rhs_sql, rhs_params = rhs
            return f"({lhs_sql} - {rhs_sql})", (*lhs_params, *rhs_params)
        raise NotSupportedError(
            f"This backend does not support {internal_type} subtraction."
        )

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
        if not self.connection.features.supports_over_clause:
            raise NotSupportedError("This backend does not support window expressions.")
        return self.window_frame_start(start), self.window_frame_end(end)

    def window_frame_range_start_end(
        self, start: int | None = None, end: int | None = None
    ) -> tuple[str, str]:
        start_, end_ = self.window_frame_rows_start_end(start, end)
        features = self.connection.features
        if features.only_supports_unbounded_with_preceding_and_following and (
            (start and start < 0) or (end and end > 0)
        ):
            raise NotSupportedError(
                f"{self.connection.display_name} only supports UNBOUNDED together with PRECEDING and "
                "FOLLOWING."
            )
        return start_, end_

    def explain_query_prefix(self, format: str | None = None, **options: Any) -> str:
        if not self.connection.features.supports_explaining_query_execution:
            raise NotSupportedError(
                "This backend does not support explaining query execution."
            )
        if format:
            supported_formats = self.connection.features.supported_explain_formats
            normalized_format = format.upper()
            if normalized_format not in supported_formats:
                msg = f"{normalized_format} is not a recognized format."
                if supported_formats:
                    msg += " Allowed formats: {}".format(
                        ", ".join(sorted(supported_formats))
                    )
                else:
                    msg += (
                        f" {self.connection.display_name} does not support any formats."
                    )
                raise ValueError(msg)
        if options:
            raise ValueError(
                "Unknown options: {}".format(", ".join(sorted(options.keys())))
            )
        return self.explain_prefix  # type: ignore[return-value]

    def insert_statement(self, on_conflict: Any = None) -> str:
        return "INSERT INTO"

    def on_conflict_suffix_sql(
        self,
        fields: list[Field],
        on_conflict: Any,
        update_fields: list[Field],
        unique_fields: list[Field],
    ) -> str:
        return ""
