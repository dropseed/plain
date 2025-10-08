from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from functools import lru_cache, partial
from typing import TYPE_CHECKING, Any

from psycopg import ClientCursor, errors  # type: ignore[import-untyped]
from psycopg.types import numeric  # type: ignore[import-untyped]
from psycopg.types.json import Jsonb  # type: ignore[import-untyped]

from plain.models.backends.base.operations import BaseDatabaseOperations
from plain.models.backends.utils import split_tzname_delta
from plain.models.constants import OnConflict
from plain.utils.regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from plain.models.fields import Field


@lru_cache
def get_json_dumps(
    encoder: type[json.JSONEncoder] | None,
) -> Callable[..., str]:
    if encoder is None:
        return json.dumps
    return partial(json.dumps, cls=encoder)


class DatabaseOperations(BaseDatabaseOperations):
    cast_char_field_without_max_length = "varchar"
    explain_prefix = "EXPLAIN"
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
    cast_data_types = {
        "PrimaryKeyField": "bigint",
    }

    integerfield_type_map = {
        "SmallIntegerField": numeric.Int2,
        "IntegerField": numeric.Int4,
        "BigIntegerField": numeric.Int8,
        "PositiveSmallIntegerField": numeric.Int2,
        "PositiveIntegerField": numeric.Int4,
        "PositiveBigIntegerField": numeric.Int8,
    }

    def unification_cast_sql(self, output_field: Field) -> str:
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

    # EXTRACT format cannot be passed in parameters.
    _extract_format_re = _lazy_re_compile(r"[A-Z_]+")

    def date_extract_sql(
        self, lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-EXTRACT
        if lookup_type == "week_day":
            # For consistency across backends, we return Sunday=1, Saturday=7.
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
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        return f"({sql})::date", params

    def datetime_cast_time_sql(
        self, sql: str, params: list[Any] | tuple[Any, ...], tzname: str | None
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        return f"({sql})::time", params

    def datetime_extract_sql(
        self,
        lookup_type: str,
        sql: str,
        params: list[Any] | tuple[Any, ...],
        tzname: str | None,
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
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
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        # https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-TRUNC
        return f"DATE_TRUNC(%s, {sql})", (lookup_type, *params)

    def time_extract_sql(
        self, lookup_type: str, sql: str, params: list[Any] | tuple[Any, ...]
    ) -> tuple[str, list[Any] | tuple[Any, ...]]:
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
        sql, params = self._convert_sql_to_tz(sql, params, tzname)
        return f"DATE_TRUNC(%s, {sql})::time", (lookup_type, *params)

    def deferrable_sql(self) -> str:
        return " DEFERRABLE INITIALLY DEFERRED"

    def fetch_returned_insert_rows(self, cursor: Any) -> list[Any]:
        """
        Given a cursor object that has just performed an INSERT...RETURNING
        statement into a table, return the tuple of returned data.
        """
        return cursor.fetchall()

    def lookup_cast(self, lookup_type: str, internal_type: str | None = None) -> str:
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

    def no_limit_value(self) -> None:
        return None

    def prepare_sql_script(self, sql: str) -> list[str]:
        return [sql]

    def quote_name(self, name: str) -> str:
        if name.startswith('"') and name.endswith('"'):
            return name  # Quoting once is enough.
        return f'"{name}"'

    def compose_sql(self, sql: str, params: Any) -> bytes:
        return ClientCursor(self.connection.connection).mogrify(sql, params)

    def set_time_zone_sql(self) -> str:
        return "SELECT set_config('TimeZone', %s, false)"

    def prep_for_iexact_query(self, x: str) -> str:
        return x

    def max_name_length(self) -> int:
        """
        Return the maximum length of an identifier.

        The maximum length of an identifier is 63 by default, but can be
        changed by recompiling PostgreSQL after editing the NAMEDATALEN
        macro in src/include/pg_config_manual.h.

        This implementation returns 63, but can be overridden by a custom
        database backend that inherits most of its behavior from this one.
        """
        return 63

    def distinct_sql(
        self, fields: list[str], params: list[Any] | tuple[Any, ...]
    ) -> tuple[list[str], list[Any]]:
        if fields:
            params = [param for param_list in params for param in param_list]
            return (["DISTINCT ON ({})".format(", ".join(fields))], params)
        else:
            return ["DISTINCT"], []

    def last_executed_query(self, cursor: Any, sql: str, params: Any) -> bytes | None:
        try:
            return self.compose_sql(sql, params)
        except errors.DataError:
            return None

    def return_insert_columns(self, fields: list[Field]) -> tuple[str, tuple[Any, ...]]:
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
        placeholder_rows_sql = (", ".join(row) for row in placeholder_rows)
        values_sql = ", ".join(f"({sql})" for sql in placeholder_rows_sql)
        return "VALUES " + values_sql

    def adapt_integerfield_value(
        self, value: int | Any | None, internal_type: str
    ) -> int | Any | None:
        if value is None or hasattr(value, "resolve_expression"):
            return value
        return self.integerfield_type_map[internal_type](value)

    def adapt_datefield_value(self, value: Any) -> Any:
        return value

    def adapt_datetimefield_value(self, value: Any) -> Any:
        return value

    def adapt_timefield_value(self, value: Any) -> Any:
        return value

    def adapt_decimalfield_value(
        self,
        value: Any,
        max_digits: int | None = None,
        decimal_places: int | None = None,
    ) -> Any:
        return value

    def adapt_ipaddressfield_value(
        self, value: str | None
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        if value:
            return ipaddress.ip_address(value)
        return None

    def adapt_json_value(self, value: Any, encoder: type[json.JSONEncoder]) -> Jsonb:
        return Jsonb(value, dumps=get_json_dumps(encoder))

    def subtract_temporals(
        self,
        internal_type: str,
        lhs: tuple[str, list[Any] | tuple[Any, ...]],
        rhs: tuple[str, list[Any] | tuple[Any, ...]],
    ) -> tuple[str, tuple[Any, ...]]:
        if internal_type == "DateField":
            lhs_sql, lhs_params = lhs
            rhs_sql, rhs_params = rhs
            params = (*lhs_params, *rhs_params)
            return f"(interval '1 day' * ({lhs_sql} - {rhs_sql}))", params
        return super().subtract_temporals(internal_type, lhs, rhs)

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
        prefix = super().explain_query_prefix(format, **options)
        if format:
            extra["FORMAT"] = format
        if extra:
            prefix += " ({})".format(
                ", ".join("{} {}".format(*i) for i in extra.items())
            )
        return prefix

    def on_conflict_suffix_sql(
        self,
        fields: list[Field],
        on_conflict: OnConflict | None,
        update_fields: list[Field],
        unique_fields: list[Field],
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
        return super().on_conflict_suffix_sql(
            fields,
            on_conflict,
            update_fields,
            unique_fields,
        )
