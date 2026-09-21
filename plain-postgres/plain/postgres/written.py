"""Written queries — the statement you wrote, rendered and checked by Postgres.

A query is either *built* — the code assembles it at runtime, which is what the
QuerySet API does — or *written*: known in full when you type it, however
complex. `Model.query.sql()` is the written side. The two meet at one seam: a
built query drops into a written one as a subquery.

Everything in a template that isn't SQL is a `{}` reference, and what the
reference names decides what it renders as:

    {Model}         the table, quoted
    {Model.field}   the qualified column, "table"."column"
    {Model.*}       every column of the model; rows become model instances
    {name}          a value, dispatched on its type (see `_render_value`)

Values are never formatted into the SQL — they bind as parameters — so there is
never an f-string here.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import dis
import string
import sys
import types
import typing
import uuid
import weakref
import zoneinfo
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import psycopg
from plain.postgres import transaction
from plain.postgres.db import get_connection
from plain.postgres.dialect import adapt_json_value, quote_name
from plain.postgres.exceptions import FieldDoesNotExist
from plain.postgres.fields.json import JSONField
from plain.postgres.fields.timezones import TimeZoneField
from plain.postgres.otel import suppress_db_tracing
from plain.postgres.query import QuerySet
from plain.postgres.registry import models_registry
from plain.postgres.sql.compiler import apply_converters, get_converters

if TYPE_CHECKING:
    from plain.exceptions import ValidationError
    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.fields import Field

__all__ = ["Fragment", "Written"]


class Fragment:
    """SQL text inlined into a written query instead of bound as a parameter.

    This is the only way to put text into a statement that the template
    doesn't spell out, so it is deliberately narrow: the text must be written
    as a literal at the construction site. Anything that reaches a `Fragment`
    from input is an injection, and a literal is the one shape that can't be.

        ACTIVE = Fragment("status = 'active' AND deleted_at IS NULL")
    """

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError(f"Fragment() takes a string literal, got {type(text)}.")
        _require_literal_argument()
        self.text = text

    def __repr__(self) -> str:
        return f"Fragment({self.text!r})"


def _require_literal_argument() -> None:
    """Refuse a Fragment built from anything but a literal string.

    Read off the construction site's bytecode: a literal argument is loaded
    with LOAD_CONST, while an f-string, a name, or a concatenation is built by
    some other instruction right before the call. This catches the mistake
    where it is made; the lint over `sql()` templates is the systematic
    version of the same rule.
    """
    try:
        frame = sys._getframe(2)  # 0 = here, 1 = Fragment.__init__, 2 = the call
    except ValueError:  # pragma: no cover - no caller frame available
        return

    previous = None
    for instruction in dis.get_instructions(frame.f_code):
        if instruction.offset >= frame.f_lasti:
            break
        previous = instruction

    if previous is not None and previous.opname != "LOAD_CONST":
        raise TypeError(
            "Fragment() takes a string literal written at the call site — "
            f"{frame.f_code.co_filename}:{frame.f_lineno} builds its argument "
            "instead. A fragment is inlined into the SQL, so it can never "
            "come from a variable or an f-string. Pass the value as a "
            "parameter with {name} instead."
        )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Rendered:
    sql: str
    params: tuple[Any, ...]
    star_models: tuple[type[Model], ...]


def _escape_percent(text: str) -> str:
    """Double every `%` in author-written text.

    psycopg substitutes parameters client-side whenever parameters are passed,
    so a literal percent (a `LIKE 'a%'`, a `format()` spec) has to arrive
    doubled. Rendered SQL from an embedded queryset is already escaped by the
    compiler that produced it, so only text from the template and from
    fragments goes through here.
    """
    return text.replace("%", "%%")


def _qualified(table: str, column: str) -> str:
    return f"{quote_name(table)}.{quote_name(column)}"


def _model_by_name(name: str, reference: str) -> type[Model]:
    matches = [
        model for model in models_registry.get_models() if model.__name__ == name
    ]
    if not matches:
        raise ValueError(
            f"{{{reference}}} names no registered model. "
            f"There is no model class called {name!r}."
        )
    if len(matches) > 1:
        paths = ", ".join(f"{m.__module__}.{m.__name__}" for m in matches)
        raise ValueError(
            f"{{{reference}}} is ambiguous — {len(matches)} registered models "
            f"are called {name!r} ({paths}). Rename one, or write the table "
            "out by hand."
        )
    return matches[0]


def _model_field(model: type[Model], field_name: str, reference: str) -> Field:
    try:
        return model._model_meta.get_forward_field(field_name)
    except FieldDoesNotExist:
        available = ", ".join(field.name for field in model._model_meta.fields)
        raise ValueError(
            f"{{{reference}}} names no field on {model.__name__}. "
            f"Its fields are: {available}."
        )


def _render(model: type[Model], template: str, values: dict[str, Any]) -> _Rendered:
    """Turn a template into one SQL string and its positional parameters.

    Everything binds positionally: psycopg refuses a statement that mixes
    `%s` with `%(name)s`, and an embedded queryset always brings `%s`. A value
    referenced twice binds twice.
    """
    parts: list[str] = []
    params: list[Any] = []
    star_models: list[type[Model]] = []

    for literal, reference, format_spec, conversion in string.Formatter().parse(
        template
    ):
        parts.append(_escape_percent(literal))

        if reference is None:
            continue

        if conversion or format_spec:
            raise ValueError(
                f"{{{reference}}} uses a format spec or conversion. A written "
                "query interpolates references and binds values — there is "
                "nothing to format."
            )

        if "." in reference:
            model_name, _, attribute = reference.partition(".")
            referenced = _model_by_name(model_name, reference)
            table = referenced.model_options.db_table
            if attribute == "*":
                star_models.append(referenced)
                parts.append(
                    ", ".join(
                        _qualified(table, field.column)
                        for field in referenced._model_meta.fields
                    )
                )
            else:
                field = _model_field(referenced, attribute, reference)
                parts.append(_qualified(table, field.column))
            continue

        named_model = _bare_model(reference)
        if named_model is not None:
            if reference in values:
                raise ValueError(
                    f"{{{reference}}} is both a registered model and a value "
                    "passed to sql(). Rename the value."
                )
            parts.append(quote_name(named_model.model_options.db_table))
            continue

        if reference not in values:
            given = ", ".join(sorted(values)) or "nothing"
            raise ValueError(
                f"{{{reference}}} has no value and names no model. "
                f"sql() was given: {given}."
            )

        _render_value(values[reference], parts, params)

    sql = "".join(parts)
    _refuse_multiple_statements(sql)
    return _Rendered(sql=sql, params=tuple(params), star_models=tuple(star_models))


def _bare_model(name: str) -> type[Model] | None:
    """The registered model called `name`, or None if nothing is."""
    matches = [
        model for model in models_registry.get_models() if model.__name__ == name
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _render_value(value: Any, parts: list[str], params: list[Any]) -> None:
    """Dispatch a `{name}` value on its type. The value type decides."""
    if isinstance(value, Fragment):
        parts.append(_escape_percent(value.text))
    elif isinstance(value, Written):
        parts.append(f"({value.sql})")
        params.extend(value.params)
    elif isinstance(value, QuerySet):
        # elide_empty=False so a queryset that can't match anything (an empty
        # `is_in`, a `none()`) still compiles to SQL that returns no rows,
        # instead of raising EmptyResultSet out of the middle of a render.
        sql, queryset_params = value.sql_query.get_compiler(elide_empty=False).as_sql()
        parts.append(f"({sql})")
        params.extend(queryset_params)
    elif isinstance(value, dict):
        parts.append("%s")
        params.append(adapt_json_value(value, None))
    else:
        # Lists included: psycopg binds one as an array, which is what
        # `= ANY({ids})` wants. Nothing is ever expanded into `IN (...)`.
        parts.append("%s")
        params.append(value)


def _refuse_multiple_statements(sql: str) -> None:
    """Refuse `...; ...` — one written query is one statement.

    Scans past the places a semicolon is ordinary text: quoted strings and
    identifiers, dollar-quoted bodies, and comments.
    """
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "'":
            index = _skip_quoted(sql, index, "'")
        elif char == '"':
            index = _skip_quoted(sql, index, '"')
        elif char == "$":
            index = _skip_dollar_quoted(sql, index)
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            index = length if end == -1 else end + 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end == -1 else end + 2
        elif char == ";":
            raise ValueError(
                "A written query is a single statement, and this one contains "
                "a ';'. Drop it (a trailing semicolon included) and make each "
                "statement its own sql() call."
            )
        else:
            index += 1


def _skip_quoted(sql: str, index: int, quote: str) -> int:
    """The index just past the string or identifier starting at `index`."""
    index += 1
    while index < len(sql):
        if sql[index] == quote:
            if sql[index + 1 : index + 2] == quote:  # '' or "" is an escape
                index += 2
                continue
            return index + 1
        index += 1
    return index


def _skip_dollar_quoted(sql: str, index: int) -> int:
    """The index just past a `$tag$ ... $tag$` body, or past a lone `$`."""
    end_of_tag = sql.find("$", index + 1)
    if end_of_tag == -1:
        return index + 1
    tag = sql[index : end_of_tag + 1]
    if not tag[1:-1].replace("_", "").isalnum() and tag != "$$":
        return index + 1
    closing = sql.find(tag, end_of_tag + 1)
    return len(sql) if closing == -1 else closing + len(tag)


# --------------------------------------------------------------------------
# What the first execution learns from cursor.description
# --------------------------------------------------------------------------

_CATALOG_SQL = """
SELECT a.attrelid, a.attnum, c.relname, a.attname
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
WHERE (a.attrelid, a.attnum) IN (SELECT unnest(%s::oid[]), unnest(%s::int2[]))
"""

# (table oid, column number) -> the model field that column belongs to, per
# connection because the oids are a property of the database.
_catalog_cache: weakref.WeakKeyDictionary[
    DatabaseConnection, dict[tuple[int, int], Field | None]
] = weakref.WeakKeyDictionary()

# One plan per (model, template, result_type). The template text is what
# decides the result columns, so a second render of the same template — with
# different values, or a different embedded queryset — reuses what the first
# execution learned.
_plans: dict[tuple[Any, str, Any], _Plan] = {}


def _strip_alias_marker(name: str) -> str:
    """`n!` and `oldest?` map to `n` and `oldest`.

    The markers are the sqlx convention for declaring in the statement what
    the catalog can't know: `!` this is not null despite appearances, `?` this
    can be null. Today they are documentation — nothing enforces them — but
    they are stripped so the column still maps onto a field by name.
    """
    if name.endswith(("!", "?")):
        return name[:-1]
    return name


@dataclasses.dataclass(frozen=True)
class _Column:
    """One result column, as the statement that produced it described it."""

    name: str
    type_oid: int
    table_oid: int
    table_column: int


def _describe_columns(cursor: Any) -> list[_Column]:
    """Read the result columns off the cursor.

    `cursor.description` carries the name and the type OID; the source table
    and column live only on the libpq result underneath it, so `pgresult` is
    the route to them. Both are read while the result is still the cursor's.
    """
    result = cursor.pgresult
    return [
        _Column(
            name=column.name,
            type_oid=column.type_code,
            table_oid=result.ftable(position),
            table_column=result.ftablecol(position),
        )
        for position, column in enumerate(cursor.description)
    ]


def _fields_for_columns(
    columns: list[_Column], connection: DatabaseConnection
) -> list[Field | None]:
    """The model field behind each result column, where there is one.

    A column that comes from a table — through aliases, joins, derived tables
    and CTEs — carries its source in `table_oid`/`table_column`. An aggregate
    or an expression carries no source, and gets no field.
    """
    pairs = {
        (column.table_oid, column.table_column)
        for column in columns
        if column.table_oid and column.table_column
    }
    resolved = _catalog_fields(connection, pairs)
    return [resolved.get((column.table_oid, column.table_column)) for column in columns]


def _catalog_fields(
    connection: DatabaseConnection, pairs: set[tuple[int, int]]
) -> dict[tuple[int, int], Field | None]:
    """Resolve `(table oid, column number)` pairs to model fields.

    One batched catalog query for everything not already known on this
    connection. Untraced: this is bookkeeping about the statement, not the
    statement.
    """
    cache = _catalog_cache.setdefault(connection, {})
    missing = sorted(pair for pair in pairs if pair not in cache)

    if missing:
        rows: list[tuple[int, int, str, str]] = []
        with suppress_db_tracing(), connection.cursor() as cursor:
            cursor.execute(
                _CATALOG_SQL,
                [[pair[0] for pair in missing], [pair[1] for pair in missing]],
            )
            rows = cursor.fetchall()

        models_by_table = {
            model.model_options.db_table: model
            for model in models_registry.get_models()
        }
        located = {
            (relation_oid, column_number): (table_name, column_name)
            for relation_oid, column_number, table_name, column_name in rows
        }
        for pair in missing:
            cache[pair] = None
            if pair not in located:
                continue
            table_name, column_name = located[pair]
            model = models_by_table.get(table_name)
            if model is None:
                continue
            cache[pair] = next(
                (
                    field
                    for field in model._model_meta.fields
                    if field.column == column_name
                ),
                None,
            )

    return {pair: cache[pair] for pair in pairs}


@dataclasses.dataclass(frozen=True)
class _Plan:
    """How to turn this statement's raw rows into results.

    Built once per template, from the first execution's `cursor.description`:
    which field converter each column needs, and how the columns become
    instances or `result_type` rows.
    """

    names: tuple[str, ...]
    converters: dict[int, tuple[list[Any], Any]]
    instance_model: type[Model] | None
    instance_fields: tuple[tuple[int, Field], ...]
    extras: tuple[tuple[int, str], ...]
    result_type: Any

    def build(
        self, rows: list[tuple[Any, ...]], connection: DatabaseConnection
    ) -> list[Any]:
        converted: Any = rows
        if self.converters:
            converted = apply_converters(iter(rows), self.converters, connection)

        if self.instance_model is not None:
            return [self._instance(row) for row in converted]

        assert self.result_type is not None
        return [
            self.result_type(**dict(zip(self.names, row, strict=True)))
            for row in converted
        ]

    def _instance(self, row: list[Any]) -> Model:
        assert self.instance_model is not None
        instance = self.instance_model.from_db(
            [field.name for _, field in self.instance_fields],
            [row[position] for position, _ in self.instance_fields],
        )
        for position, attribute in self.extras:
            setattr(instance, attribute, row[position])
        return instance


def _build_plan(
    *,
    model: type[Model],
    template: str,
    instance_model: type[Model] | None,
    result_type: Any,
    columns: list[_Column],
    connection: DatabaseConnection,
) -> _Plan:
    names = tuple(_strip_alias_marker(column.name) for column in columns)
    fields = _fields_for_columns(columns, connection)
    converters = get_converters(
        [
            None if field is None else field.get_col(field.model.model_options.db_table)
            for field in fields
        ],
        connection,
    )

    if instance_model is not None:
        instance_fields = tuple(
            (position, field)
            for position, field in enumerate(fields)
            if field is not None and field.model is instance_model
        )
        taken = {position for position, _ in instance_fields}
        extras = tuple(
            (position, name)
            for position, name in enumerate(names)
            if position not in taken
        )
        selected = {field.name for _, field in instance_fields}
        if "id" not in selected:
            raise TypeError(
                f"A statement that returns {instance_model.__name__} instances "
                f"has to select the primary key. Use {{{instance_model.__name__}.*}}."
            )
        return _Plan(
            names=names,
            converters=converters,
            instance_model=instance_model,
            instance_fields=instance_fields,
            extras=extras,
            result_type=None,
        )

    if result_type is None:
        raise TypeError(
            f"This statement returns columns ({', '.join(names)}) and nothing "
            "says what a row is. Select {"
            + model.__name__
            + ".*} to get instances, or pass result_type= a dataclass."
        )

    _check_result_type(result_type, names, columns, fields, connection)
    return _Plan(
        names=names,
        converters=converters,
        instance_model=None,
        instance_fields=(),
        extras=(),
        result_type=result_type,
    )


# --------------------------------------------------------------------------
# Result type verification
# --------------------------------------------------------------------------

# The Python type psycopg hands back for each type OID, read against the
# adapters Plain installs -- notably jsonb, which Plain loads as text on
# purpose and a JSONField's converter parses.
_OID_TO_PYTHON: dict[int, type] = {
    16: bool,
    17: bytes,
    20: int,
    21: int,
    23: int,
    25: str,
    114: dict,
    700: float,
    701: float,
    869: str,  # inet, loaded as text by plain.postgres.adapters
    1043: str,
    1082: datetime.date,
    1083: datetime.time,
    1114: datetime.datetime,
    1184: datetime.datetime,
    1186: datetime.timedelta,
    1700: decimal.Decimal,
    2950: uuid.UUID,
    3802: str,  # jsonb, likewise text
}


class _AnyJson:
    """The stand-in for a parsed JSON value, which can be anything."""


def _python_type_for_column(
    column: _Column, field: Field | None, connection: DatabaseConnection
) -> Any:
    """The Python type a row will actually carry in this column.

    The OID says what psycopg loads; a field converter then says what it turns
    into — a JSONField parses the text psycopg loaded, a TimeZoneField builds
    a ZoneInfo, an encrypted field decrypts to its own type.
    """
    if field is not None and field.get_db_converters(connection):
        if isinstance(field, JSONField):
            return _AnyJson
        if isinstance(field, TimeZoneField):
            return zoneinfo.ZoneInfo

    assert connection.connection is not None
    info = connection.connection.adapters.types.get(column.type_oid)
    if info is not None and info.array_oid == column.type_oid:
        return list

    return _OID_TO_PYTHON.get(column.type_oid)


def _annotation_base(annotation: Any) -> Any:
    """`str | None` -> `str`, `list[int]` -> `list`, `dict[str, Any]` -> `dict`."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            annotation = args[0]
        else:
            return None  # a real union: nothing single to compare against
    return typing.get_origin(annotation) or annotation


def _describe_result_type(result_type: Any) -> str:
    hints = typing.get_type_hints(result_type)
    lines = [
        f"    {field.name}: {_format_annotation(hints.get(field.name, Any))}"
        for field in dataclasses.fields(result_type)
        if field.init
    ]
    return f"{result_type.__name__}:\n" + "\n".join(lines)


def _format_annotation(annotation: Any) -> str:
    return getattr(annotation, "__name__", str(annotation)).replace("typing.", "")


def _check_result_type(
    result_type: Any,
    names: tuple[str, ...],
    columns: list[_Column],
    fields: list[Field | None],
    connection: DatabaseConnection,
) -> None:
    """Check the result columns against the dataclass, by name then by type."""
    if len(set(names)) != len(names):
        raise TypeError(
            f"This statement returns duplicate column names ({', '.join(names)}), "
            f"and {result_type.__name__} maps columns by name. Alias them apart."
        )

    declared = [field.name for field in dataclasses.fields(result_type) if field.init]
    missing = [name for name in declared if name not in names]
    unexpected = [name for name in names if name not in declared]
    if missing or unexpected:
        problems = []
        if missing:
            problems.append(f"no column for {', '.join(missing)}")
        if unexpected:
            problems.append(f"no field for column {', '.join(unexpected)}")
        raise TypeError(
            f"This statement doesn't match {result_type.__name__} — "
            f"{'; '.join(problems)}. It returned {', '.join(names)}, and the "
            f"dataclass declares\n{_describe_result_type(result_type)}"
        )

    hints = typing.get_type_hints(result_type)
    for position, name in enumerate(names):
        expected = _python_type_for_column(
            columns[position], fields[position], connection
        )
        if expected is None or expected is _AnyJson:
            continue
        annotated = _annotation_base(hints.get(name, Any))
        if annotated in (Any, object, None):
            continue
        if annotated is not expected:
            raise TypeError(
                f"Column {name!r} comes back as {expected.__name__}, but "
                f"{result_type.__name__} declares it "
                f"{_format_annotation(hints[name])}. The statement returns\n"
                f"{_describe_result_type(result_type)}"
            )


# --------------------------------------------------------------------------
# The statement
# --------------------------------------------------------------------------


def _integrity_error_to_validation_error(
    model: type[Model], exc: psycopg.IntegrityError
) -> ValidationError | None:
    """The ValidationError a declared constraint describes for this violation.

    The same mapping `Model.create()`/`Model.update()` do, minus the parts
    that need the row being written: a written statement has no instance, so
    only constraints that can describe themselves — check and unique — map,
    and anything else re-raises as the original IntegrityError.
    """
    constraint_name = exc.diag.constraint_name
    if not constraint_name:
        return None
    constraint = model._model_meta.constraints_by_name.get(constraint_name)
    if constraint is None:
        return None
    try:
        instance = model()
    except Exception:
        return None
    error = constraint._db_violation_error(instance, model)
    if error is None:
        return None
    from plain.exceptions import ValidationError

    return ValidationError(error.update_error_dict({}))


class Written[R]:
    """One written statement, rendered and ready to run.

    Immutable, and it runs at most once: iterate it and the rows are cached,
    the way a queryset caches its result. Call `sql()` again to run it again —
    which matters for writes, where a second iteration must not insert twice.

    It renders when it is constructed, so an unknown reference or a missing
    value fails at the call site, and so it can be embedded in another
    statement as `{name}` without running.
    """

    def __init__(
        self,
        *,
        model: type[Model],
        template: str,
        values: dict[str, Any],
        result_type: Any = None,
    ) -> None:
        if result_type is not None and not (
            isinstance(result_type, type) and dataclasses.is_dataclass(result_type)
        ):
            raise TypeError("sql(result_type=...) requires a dataclass.")

        rendered = _render(model, template, values)

        star_models = dict.fromkeys(rendered.star_models)
        if star_models and result_type is not None:
            raise TypeError(
                "sql() takes {Model.*} or result_type=, not both — "
                "{Model.*} already says a row is a model instance."
            )
        if len(star_models) > 1:
            names = ", ".join(model.__name__ for model in star_models)
            raise TypeError(
                f"sql() selects every column of more than one model ({names}), "
                "so a row can't be one instance. Select the columns you need "
                "and pass result_type= a dataclass."
            )

        self._model = model
        self._template = template
        self._result_type = result_type
        self._instance_model = next(iter(star_models), None)
        self._sql = rendered.sql
        self._params = rendered.params
        self._result_cache: list[R] | None = None
        self._row_count: int | None = None

    # -- what it renders to -------------------------------------------------

    @property
    def sql(self) -> str:
        """The rendered statement, with `%s` where each parameter binds."""
        return self._sql

    @property
    def params(self) -> tuple[Any, ...]:
        """The parameters, in the order they bind."""
        return self._params

    def __repr__(self) -> str:
        return f"<Written: {self._sql}>"

    # -- running it ---------------------------------------------------------

    def _fetch(self) -> list[R]:
        if self._result_cache is not None:
            return self._result_cache

        connection = get_connection()
        with connection.cursor() as cursor:
            try:
                with transaction.mark_for_rollback_on_error():
                    cursor.execute(self._sql, list(self._params))
            except psycopg.IntegrityError as exc:
                error = _integrity_error_to_validation_error(self._model, exc)
                if error is not None:
                    raise error from exc
                raise
            self._row_count = cursor.rowcount
            columns = (
                _describe_columns(cursor) if cursor.description is not None else None
            )
            rows = cursor.fetchall() if columns is not None else []

        if columns is None:
            # A write with no RETURNING: there is nothing to yield.
            self._result_cache = []
            return self._result_cache

        key = (self._model, self._template, self._result_type)
        plan = _plans.get(key)
        if plan is None:
            plan = _build_plan(
                model=self._model,
                template=self._template,
                instance_model=self._instance_model,
                result_type=self._result_type,
                columns=columns,
                connection=connection,
            )
            _plans[key] = plan

        self._result_cache = plan.build(rows, connection)
        return self._result_cache

    def _scalar(self, sql: str) -> Any:
        connection = get_connection()
        with connection.cursor() as cursor:
            with transaction.mark_for_rollback_on_error():
                cursor.execute(sql, list(self._params))
            row = cursor.fetchone()
        assert row is not None
        return row[0]

    def __iter__(self) -> Iterator[R]:
        return iter(self._fetch())

    def __len__(self) -> int:
        return len(self._fetch())

    def __bool__(self) -> bool:
        return bool(self._fetch())

    def all(self) -> list[R]:
        """Every row, as a list."""
        return list(self._fetch())

    def first(self) -> R | None:
        """The first row, or None if the statement returned none."""
        rows = self._fetch()
        return rows[0] if rows else None

    def get(self) -> R:
        """The one row the statement returned.

        A statement that returns model instances raises that model's
        `DoesNotExist`/`MultipleObjectsReturned`, the same as `QuerySet.get()`.
        A `result_type` statement has no model to raise for, so it raises
        `ValueError`.
        """
        rows = self._fetch()
        if len(rows) == 1:
            return rows[0]
        if self._instance_model is not None:
            if not rows:
                raise self._instance_model.DoesNotExist(
                    f"{self._instance_model.model_options.object_name} matching "
                    "query does not exist."
                )
            raise self._instance_model.MultipleObjectsReturned(
                f"get() returned more than one "
                f"{self._instance_model.model_options.object_name} -- it "
                f"returned {len(rows)}!"
            )
        if not rows:
            raise ValueError("get() found no rows.")
        raise ValueError(f"get() found {len(rows)} rows, not one.")

    def count(self) -> int:
        """How many rows the statement returns."""
        if self._result_cache is not None:
            return len(self._result_cache)
        return self._scalar(f'SELECT count(*) FROM ({self._sql}) "written"')

    def exists(self) -> bool:
        """Whether the statement returns any row at all."""
        if self._result_cache is not None:
            return bool(self._result_cache)
        return self._scalar(f'SELECT EXISTS(SELECT 1 FROM ({self._sql}) "written")')

    def execute(self) -> int:
        """Run the statement and return how many rows it affected.

        This is the write without a RETURNING clause — the rows are gone
        either way, and the count is what an `UPDATE` or `DELETE` has to say.
        """
        self._fetch()
        assert self._row_count is not None
        return self._row_count
