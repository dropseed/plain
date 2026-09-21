"""Written queries — the statement you wrote, rendered and checked by Postgres.

A query is either *built* — the code assembles it at runtime, which is what the
QuerySet API does — or *written*: known in full when you type it, however
complex. `Model.query.sql()` is the written side. The two meet at one seam: a
built query drops into a written one as a subquery.

The statement is a t-string (PEP 750), so Python does the interpolation and
hands this module the literal text and each interpolated *object* separately.
What the object is decides what it renders as:

    {Model}              the table, quoted
    {Model:*}            every column of the model; rows become model instances
    {Model.field}        the qualified column, "table"."column"
    {Model.field:name}   just the column, for an INSERT list or an UPDATE SET
    {queryset}           the built query, embedded as a subquery
    {statement}          another sql() statement, embedded the same way
    {template}           another t-string, rendered inline
    {value}              anything else, bound as a parameter

What that guarantees, exactly: the literal halves of a t-string are SQL the
author wrote in the source, and every interpolated object is dispatched on
its type, where a value always binds as a parameter. `sql()` takes a
`Template`, so a `str` can't be passed at all — the type checker refuses a
literal, an f-string and a runtime-built string alike.

The one way to put runtime text into a statement is to build a `Template`
from a string yourself (`Template(text)`, or concatenating one onto a
t-string). That is a deliberate escape hatch, and it is exactly what must
never be done with anything that came from outside the program.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import datetime
import decimal
import json
import types
import typing
import uuid
import weakref
import zoneinfo
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from string.templatelib import Interpolation, Template
from typing import TYPE_CHECKING, Any, Self

import psycopg
from plain.postgres import transaction
from plain.postgres.base import Model
from plain.postgres.db import get_connection
from plain.postgres.dialect import adapt_json_value, quote_name
from plain.postgres.fields import Field
from plain.postgres.fields.encrypted import _ENCRYPTED_PREFIX
from plain.postgres.fields.json import JSONField
from plain.postgres.fields.related_descriptors import (
    ForwardForeignKeyDescriptor,
    ForwardManyToManyDescriptor,
)
from plain.postgres.fields.related_managers import BaseRelatedManager
from plain.postgres.fields.reverse_descriptors import BaseReverseDescriptor
from plain.postgres.fields.timezones import TimeZoneField
from plain.postgres.otel import db_span, suppress_db_tracing
from plain.postgres.query import QuerySet, prefetch_objects
from plain.postgres.registry import models_registry
from plain.postgres.sql.compiler import apply_converters, get_converters

if TYPE_CHECKING:
    from collections.abc import Generator

    from plain.exceptions import ValidationError
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.query import Prefetch

__all__ = ["Written"]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _StarExpansion:
    """What one `{Model:*}` put into the select list.

    The fields are in declared order and the column names are theirs, which is
    how the result columns are found again — the expansion decides which
    positions are the instance, never the catalog.
    """

    model: type[Model]
    fields: tuple[Field, ...]
    columns: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class _Rendered:
    sql: str
    bind_sql: str
    params: tuple[Any, ...]
    stars: tuple[_StarExpansion, ...]


class _Sql:
    """The statement being rendered, in the two forms it needs.

    `bind` is what psycopg is handed: it parses `%s` placeholders whether it
    binds client- or server-side, so a literal `%` in author text has to arrive
    doubled. `display` is the same statement as written — what `.sql`, the
    query span and the logs show.
    """

    def __init__(self) -> None:
        self.bind: list[str] = []
        self.display: list[str] = []

    def author(self, text: str) -> None:
        """Text the author wrote: template literals and fragments."""
        self.bind.append(text.replace("%", "%%"))
        self.display.append(text)

    def rendered(self, sql: str, display: str | None = None) -> None:
        """SQL this module produced: identifiers, placeholders, subqueries."""
        self.bind.append(sql)
        self.display.append(sql if display is None else display)


def _qualified(table: str, column: str) -> str:
    return f"{quote_name(table)}.{quote_name(column)}"


def _render(template: Template) -> _Rendered:
    """Turn a t-string into one SQL statement and its positional parameters.

    Everything binds positionally: psycopg refuses a statement that mixes `%s`
    with `%(name)s`, and an embedded queryset always brings `%s`. A value
    interpolated twice binds twice.
    """
    sql = _Sql()
    params: list[Any] = []
    stars: list[_StarExpansion] = []

    _render_template(template, sql, params, stars)

    binds_parameters = bool(params)
    return _Rendered(
        # The trailing `;` comes off both forms, so `.sql` and the span show
        # the statement that actually ran.
        sql=_one_statement("".join(sql.display), binds_parameters=binds_parameters),
        bind_sql=_one_statement("".join(sql.bind), binds_parameters=binds_parameters),
        params=tuple(params),
        stars=tuple(stars),
    )


def _render_template(
    template: Template,
    sql: _Sql,
    params: list[Any],
    stars: list[_StarExpansion],
) -> None:
    """Render one t-string into the statement being built.

    A `Template` alternates literal text and interpolations, starting and
    ending with text — `strings` always has exactly one more entry than
    `interpolations`.
    """
    for literal, interpolation in zip(template.strings, template.interpolations):
        sql.author(literal)
        _render_interpolation(interpolation, sql, params, stars)
    sql.author(template.strings[-1])


# The relation accessors a model class carries. A forward foreign key is not
# one of them: it has a column of its own, and `_field_of` renders it.
_RELATIONS = (
    ForwardManyToManyDescriptor,
    BaseReverseDescriptor,
    BaseRelatedManager,
)

# Everything a literal expression can be made of. A node outside this set --
# a name, an attribute, a call, a subscript -- means the braces refer to
# something in the program.
_LITERAL_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.Set,
    ast.UnaryOp,
    ast.BinOp,
    ast.unaryop,
    ast.operator,
    ast.expr_context,
)


def _interpolates_a_literal(expression: str) -> bool:
    """Whether the braces hold a literal instead of naming anything.

    `'^\\d{2}$'` is a regex the author forgot to double the braces in, and
    Python read `{2}` as an interpolation of the int 2. By the time it is a
    value there is no way to tell that from a parameter someone meant to
    bind, so the source text between the braces is what answers it: nothing
    in the program is named, so nothing was meant to bind.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return False
    return all(isinstance(node, _LITERAL_NODES) for node in ast.walk(tree))


def _render_interpolation(
    interpolation: Interpolation,
    sql: _Sql,
    params: list[Any],
    stars: list[_StarExpansion],
) -> None:
    """Render one `{...}` on what its value *is*. The value type decides.

    Errors quote `interpolation.expression` — the source text between the
    braces — so a message names what the author wrote.
    """
    written = interpolation.expression
    value = interpolation.value
    format_spec = interpolation.format_spec

    if _interpolates_a_literal(written):
        raise ValueError(
            f"{{{written}}} interpolates a literal, which is never a value "
            "worth binding — it is almost always a brace that should have "
            "been doubled. A literal brace in SQL — a regex quantifier like "
            "\\d{2}, an array or jsonb literal — is written `{{`, and `}` is "
            "written `}}`."
        )

    if interpolation.conversion:
        raise ValueError(
            f"{{{written}!{interpolation.conversion}}} uses a conversion. A "
            "written query interpolates models and binds values — there is "
            "nothing to convert."
        )

    if isinstance(value, type) and issubclass(value, Model):
        _render_model(value, format_spec, written, sql, stars)
        return

    field = _field_of(value)
    if field is not None:
        _render_field(field, format_spec, written, sql)
        return

    if isinstance(value, Template):
        if format_spec:
            raise ValueError(
                f"{{{written}:{format_spec}}} — a nested template takes no "
                "format spec; it renders as the SQL it spells out."
            )
        _render_template(value, sql, params, stars)
        return

    if isinstance(value, Model):
        # Caught here rather than at execute, where psycopg's "cannot adapt
        # type" names the class and nothing else.
        raise TypeError(
            f"{{{written}}} is a {type(value).__name__} instance, not something "
            f"a statement can hold. Interpolate a field of it "
            f"({{{written}.id}}), or the value you meant."
        )

    if isinstance(value, _RELATIONS):
        raise TypeError(
            f"{{{written}}} is a relation, not a column. A written query has no "
            "relations to follow — write the JOIN out and interpolate the "
            "related model's own columns."
        )

    if format_spec:
        raise ValueError(
            f"{{{written}:{format_spec}}} — a value takes no format spec. It "
            "binds as a parameter; formatting it would put it in the SQL. (If "
            "you meant a literal brace in the SQL, double it: `{{` and `}}`.)"
        )

    _render_value(value, sql, params)


def _field_of(value: Any) -> Field | None:
    """The model field this interpolation names, if it names one.

    `Widget.name` at class level *is* the `Field`. A foreign key is a
    descriptor instead — that is what serves `Post.author.email` traversal —
    and the field it wraps is the one that owns the `_id` column.
    """
    if isinstance(value, Field):
        return value
    if isinstance(value, ForwardForeignKeyDescriptor):
        return value._field
    return None


def _render_model(
    model: type[Model],
    format_spec: str,
    written: str,
    sql: _Sql,
    stars: list[_StarExpansion],
) -> None:
    """`{Model}` is the table; `{Model:*}` is every column of it."""
    table = model.model_options.db_table

    if not format_spec:
        sql.rendered(quote_name(table))
        return

    if format_spec != "*":
        raise ValueError(
            f"{{{written}:{format_spec}}} — the only format spec a model takes "
            "is `:*`, which expands to every column and makes each row an "
            "instance."
        )

    fields = tuple(model._model_meta.fields)
    stars.append(
        _StarExpansion(
            model=model,
            fields=fields,
            columns=tuple(field.column for field in fields),
        )
    )
    sql.rendered(", ".join(_qualified(table, field.column) for field in fields))


def _render_field(field: Field, format_spec: str, written: str, sql: _Sql) -> None:
    """`{Model.field}` is the qualified column; `{Model.field:name}` is bare."""
    if field.is_lookup_reference:
        # `WidgetTag.widget.name` is the traversal `where()` follows through a
        # join it builds. A written statement builds nothing, and the field
        # handed back doesn't even carry the table its column lives on.
        raise ValueError(
            f"{{{written}}} is a traversal, not a column of this statement. A "
            "written query has no relations to follow — write the JOIN out and "
            "interpolate the related model's own field."
        )

    if "model" not in field.__dict__:
        raise ValueError(
            f"{{{written}}} is a field that belongs to no model, so there is no "
            "table to qualify its column with. Interpolate a model's own field."
        )

    if not format_spec:
        sql.rendered(_qualified(field.model.model_options.db_table, field.column))
        return

    if format_spec != "name":
        raise ValueError(
            f"{{{written}:{format_spec}}} — the only format spec a column takes "
            "is `:name`, which renders the column on its own for an INSERT list "
            "or an UPDATE SET target."
        )

    # The bare column: an INSERT column list and an UPDATE SET target can't
    # take a qualified name.
    sql.rendered(quote_name(field.column))


def _render_value(value: Any, sql: _Sql, params: list[Any]) -> None:
    """Render a value that names nothing in the models."""
    if isinstance(value, Written):
        # The newlines matter, the same way they do in `_wrap`: the embedded
        # statement can end in a `-- comment`, and the `)` would be inside it.
        sql.rendered(f"(\n{value._bind_sql}\n)", f"(\n{value.sql}\n)")
        params.extend(value.params)
    elif isinstance(value, QuerySet):
        # elide_empty=False so a queryset that can't match anything (an empty
        # `is_in`, a `none()`) still compiles to SQL that returns no rows,
        # instead of raising EmptyResultSet out of the middle of a render.
        compiled, queryset_params = value.sql_query.get_compiler(
            elide_empty=False
        ).as_sql()
        sql.rendered(f"({compiled})")
        params.extend(queryset_params)
    elif isinstance(value, dict):
        sql.rendered("%s")
        params.append(adapt_json_value(value, None))
    else:
        # Lists included: psycopg binds one as an array, which is what
        # `= ANY({ids})` wants. Nothing is ever expanded into `IN (...)`.
        sql.rendered("%s")
        params.append(value)


def _one_statement(sql: str, *, binds_parameters: bool) -> str:
    """One written query is one statement.

    A statement that binds a parameter goes to the server over the extended
    query protocol, which carries exactly one command, so Postgres refuses
    `SELECT 1; DROP TABLE x` itself. With no parameters to bind psycopg sends
    the statement as a simple query instead, and the server will happily run
    both halves — so that case is refused here.

    The check is deliberately blunt: any `;` left after the trailing one comes
    off is refused, quoted or not. A template is the statement the author
    wrote, so the cost of being wrong is a rewrite, not a mystery.
    """
    sql = sql.rstrip().removesuffix(";")
    if not binds_parameters and ";" in sql:
        raise ValueError(
            "A written query is a single statement, and this one contains a "
            "';'. Split it into separate sql() calls. (A ';' inside a SQL "
            "string literal counts too: interpolate the string instead, so it "
            "binds as a parameter.)"
        )
    return sql


def _wrap(sql: str, suffix: str = "", *, prefix: str = "SELECT * FROM ") -> str:
    """Put a statement in a derived table.

    The newlines matter: a statement can end in a `-- comment`, and anything
    appended to that line would be inside it.
    """
    return f'{prefix}(\n{sql}\n) "written"{" " + suffix if suffix else ""}'


def _leading_keyword(sql: str) -> str:
    """The first word of a statement, past whitespace and leading comments."""
    index = 0
    while index < len(sql):
        if sql[index].isspace():
            index += 1
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end == -1 else end + 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = len(sql) if end == -1 else end + 2
        else:
            break
    rest = sql[index:]
    if rest.startswith("("):
        return "("
    return rest.split(maxsplit=1)[0].upper() if rest.split() else ""


# --------------------------------------------------------------------------
# Executing
# --------------------------------------------------------------------------


@contextmanager
def _written_cursor(connection: DatabaseConnection) -> Generator[Any]:
    """A cursor that binds this statement's parameters server-side.

    Plain's connections default to `ClientCursor` — client-side binding, no
    server-side statement of any kind, which is what keeps them safe behind a
    transaction-mode pooler like pgbouncer. A written statement uses psycopg's
    ordinary `Cursor` instead, for one reason: the extended query protocol
    carries exactly one command, so Postgres refuses a second statement
    smuggled into a template whenever the statement binds a parameter. (With
    no parameters psycopg sends a simple query, so `_one_statement` covers
    that case.) It stays pooler-safe because the statement is UNNAMED and
    one-shot — `prepare=True` is the named kind that isn't, and every execute
    here passes `prepare=False` to say so.

    Wrapped in Plain's own cursor wrapper so the statement is logged and
    guarded like every other query.
    """
    connection.ensure_connection()
    assert connection.connection is not None
    with connection._prepare_cursor(psycopg.Cursor(connection.connection)) as cursor:
        yield cursor


# --------------------------------------------------------------------------
# What the result columns are, and where they came from
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

# One plan per result-column signature — the names, types and sources the
# statement actually came back with. Two renders of the same template that
# return the same columns share a plan; anything that changes the columns
# (a different embedded queryset, a schema change) builds a new one, and the
# cache can only grow to the number of distinct result shapes.
#
# Per connection, like the catalog cache and for the same reason: a signature
# carries table OIDs, and those belong to one database. Two databases with the
# same schema -- a checkout and the fork it came from -- assign them
# independently.
_plans: weakref.WeakKeyDictionary[DatabaseConnection, dict[_Signature, _Plan]] = (
    weakref.WeakKeyDictionary()
)


@dataclasses.dataclass(frozen=True)
class _Column:
    """One result column, as the statement that produced it described it."""

    name: str
    type_oid: int
    table_oid: int
    table_column: int


type _Signature = tuple[tuple[str, int, int, int], ...]


def _signature(columns: list[_Column]) -> _Signature:
    return tuple(
        (column.name, column.type_oid, column.table_oid, column.table_column)
        for column in columns
    )


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


def _fields_for_columns(
    columns: list[_Column], connection: DatabaseConnection
) -> list[Field | None]:
    """The model field behind each result column, where there is one.

    A column that comes from a table — through aliases, joins, derived tables
    and CTEs — carries its source in `table_oid`/`table_column`. An aggregate,
    an expression, or a branch of a UNION carries no source, and gets no field:
    provenance is what attaches converters, so a column without it is returned
    exactly as Postgres sent it.
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


# --------------------------------------------------------------------------
# The plan: how this statement's rows become results
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Plan:
    """How to turn this statement's raw rows into results.

    Built from the first execution's result columns and reused for as long as
    a statement comes back with the same ones.
    """

    signature: _Signature
    names: tuple[str, ...]
    converters: dict[int, tuple[list[Any], Any]]
    decryptable: tuple[int, ...]
    star: _StarExpansion | None
    star_start: int
    extras: tuple[tuple[int, str], ...]
    stars: tuple[_StarExpansion, ...]
    result_type: Any

    def build(
        self, rows: list[tuple[Any, ...]], connection: DatabaseConnection
    ) -> list[Any]:
        self._refuse_ciphertext(rows)

        converted: Any = rows
        if self.converters:
            converted = apply_converters(iter(rows), self.converters, connection)

        if self.star is not None:
            return [self._instance(row) for row in converted]

        assert self.result_type is not None
        return [
            self.result_type(**dict(zip(self.names, row, strict=True)))
            for row in converted
        ]

    def _refuse_ciphertext(self, rows: list[tuple[Any, ...]]) -> None:
        """Refuse a column that lost its source and came back as ciphertext.

        Provenance is what attaches the decrypting converter, and an
        expression, an aggregate or a UNION drops it — so
        `coalesce({Secret.api_key}, '')` would otherwise hand back the stored
        token as a perfectly well-typed `str`.

        Every value in a column that *could* hold one is checked, on every
        execution: the first row of the first execution is no evidence (it can
        be NULL, or there can be no rows at all), and a plan is reused by any
        statement with the same column signature.

        The cost is a false positive on a plain text column whose value
        happens to start with the prefix, which is a refusal to hand back a
        string that looks exactly like a leaked secret.
        """
        if not self.decryptable:
            return
        for row in rows:
            for position in self.decryptable:
                value = row[position]
                if isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX):
                    raise TypeError(
                        f"Column {self.names[position]!r} holds an encrypted "
                        "value but lost track of the column it came from, so "
                        "nothing can decrypt it — an expression, an aggregate "
                        "or a UNION does that. Select it as {Model.field} on "
                        "its own."
                    )

    def _instance(self, row: Sequence[Any]) -> Model:
        assert self.star is not None
        width = len(self.star.fields)
        instance = self.star.model.from_db(
            [field.name for field in self.star.fields],
            list(row[self.star_start : self.star_start + width]),
        )
        for position, attribute in self.extras:
            setattr(instance, attribute, row[position])
        return instance


def _build_plan(
    *,
    model: type[Model],
    stars: tuple[_StarExpansion, ...],
    result_type: Any,
    columns: list[_Column],
    connection: DatabaseConnection,
) -> _Plan:
    names = tuple(_strip_alias_marker(column.name) for column in columns)
    fields = _fields_for_columns(columns, connection)
    converters = _converters_for(columns, fields, connection)
    decryptable = _decryptable_positions(columns, fields)

    if stars:
        star = stars[0]
        star_start = _star_start(names, fields, star)
        taken = range(star_start, star_start + len(star.fields))
        extras = tuple(
            (position, name)
            for position, name in enumerate(names)
            if position not in taken
        )
        for _, name in extras:
            if name in star.columns:
                raise TypeError(
                    f"This statement selects {{{star.model.__name__}:*}} and "
                    f"another column called {name!r}, which would overwrite the "
                    "instance's own. Alias the extra column."
                )
        return _Plan(
            signature=_signature(columns),
            names=names,
            converters=converters,
            decryptable=decryptable,
            star=star,
            star_start=star_start,
            extras=extras,
            stars=stars,
            result_type=None,
        )

    if result_type is None:
        star = f"{{{model.__name__}:*}}"
        raise TypeError(
            f"This statement returns columns ({', '.join(names)}) and nothing "
            f"says what a row is. Select {star} to get instances, or pass "
            "result_type= a dataclass."
        )

    _check_result_type(result_type, names, columns, fields, connection)
    return _Plan(
        signature=_signature(columns),
        names=names,
        converters=converters,
        decryptable=decryptable,
        star=None,
        star_start=0,
        extras=(),
        stars=(),
        result_type=result_type,
    )


def _star_start(
    names: tuple[str, ...], fields: list[Field | None], star: _StarExpansion
) -> int:
    """Where `{Model:*}`'s columns start in the result.

    The expansion emitted the model's columns, in declared order, as one run —
    so the run of result columns with those names *is* the instance. Reading it
    back this way means the instance's fields are the ones the template asked
    for, not whichever columns the catalog happens to trace to this model: a
    self-join, a UNION branch, or another table with the same column names
    can't shift them.
    """
    width = len(star.columns)
    candidates = [
        start
        for start in range(len(names) - width + 1)
        if tuple(names[start : start + width]) == star.columns
    ]
    if not candidates:
        raise TypeError(
            f"This statement returns ({', '.join(names)}), which doesn't "
            f"contain {star.model.__name__}'s columns "
            f"({', '.join(star.columns)}) in order. If the "
            f"{{{star.model.__name__}:*}} is inside a subquery, select the "
            "columns you want in the outer statement and pass result_type= a "
            "dataclass; otherwise something renamed them, and a "
            f"{{{star.model.__name__}:*}} row can't be aliased."
        )
    if len(candidates) > 1:
        # Two runs of columns have those names. Provenance breaks the tie when
        # it survived; when it didn't, the statement is genuinely ambiguous.
        confirmed = [
            start
            for start in candidates
            if all(
                fields[start + offset] is star.fields[offset] for offset in range(width)
            )
        ]
        if len(confirmed) != 1:
            raise TypeError(
                f"This statement returns {star.model.__name__}'s columns "
                f"({', '.join(star.columns)}) more than once, so which run is "
                "the instance is ambiguous. Alias the other one's columns."
            )
        return confirmed[0]
    return candidates[0]


def _converters_for(
    columns: list[_Column],
    fields: list[Field | None],
    connection: DatabaseConnection,
) -> dict[int, tuple[list[Any], Any]]:
    """The converter each column needs before it becomes a value.

    A column with a field gets that field's converters — decryption, JSON
    parsing, a timezone. A `json`/`jsonb` column with no field gets parsed
    anyway: Plain loads `jsonb` as text on purpose (a `JSONField`'s converter
    is normally what parses it), and handing back the raw text because the
    column came out of an expression would be a surprise, not a rule.
    """
    converters = get_converters(
        [
            None if field is None else field.get_col(field.model.model_options.db_table)
            for field in fields
        ],
        connection,
    )
    for position, (column, field) in enumerate(zip(columns, fields, strict=True)):
        if field is None and column.type_oid in _JSON_OIDS:
            converters[position] = ([_parse_json], None)
    return converters


_JSON_OIDS = frozenset({114, 3802})  # json, jsonb


def _parse_json(value: Any, expression: Any, connection: Any) -> Any:
    """Parse a `json`/`jsonb` column that no field converter claimed."""
    if isinstance(value, str | bytes):
        return json.loads(value)
    return value


# The column types an encrypted value could arrive in: it is stored as text,
# and an expression can put it through a json type on the way out.
_MAYBE_CIPHERTEXT_OIDS = frozenset({25, 1043, 114, 3802})  # text, varchar, json, jsonb


def _decryptable_positions(
    columns: list[_Column], fields: list[Field | None]
) -> tuple[int, ...]:
    """The positions where an undecrypted value could turn up.

    A column with a field is decrypted by that field's converter. One without
    has nothing to decrypt it, so if it is text-shaped its values get checked.
    """
    return tuple(
        position
        for position, (column, field) in enumerate(zip(columns, fields, strict=True))
        if field is None and column.type_oid in _MAYBE_CIPHERTEXT_OIDS
    )


# --------------------------------------------------------------------------
# Result type verification
# --------------------------------------------------------------------------

# The Python type psycopg hands back for each type OID, read against the
# adapters Plain installs.
_OID_TO_PYTHON: dict[int, type] = {
    16: bool,
    17: bytes,
    20: int,
    21: int,
    23: int,
    25: str,
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
}


class _AnyJson:
    """The stand-in for a parsed JSON value, which can be anything."""


def _python_type_for_column(
    column: _Column, field: Field | None, connection: DatabaseConnection
) -> Any:
    """The Python type a row will actually carry in this column.

    The OID says what psycopg loads; a converter then says what it turns into —
    JSON is parsed, a TimeZoneField builds a ZoneInfo, an encrypted field
    decrypts to its own type.
    """
    if column.type_oid in _JSON_OIDS:
        return _AnyJson

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


def _type_hints(result_type: Any) -> dict[str, Any]:
    """`result_type`'s annotations, resolved.

    They are resolved late — the dataclass may be defined anywhere — so a name
    that doesn't resolve surfaces here, where the statement can say so.
    """
    try:
        return typing.get_type_hints(result_type)
    except NameError as exc:
        raise TypeError(
            f"sql(result_type={result_type.__name__}) can't read its "
            f"annotations: {exc}. Every name they use has to be importable at "
            f"runtime — move it out of `if TYPE_CHECKING` for this dataclass."
        ) from exc


def _describe_result_type(result_type: Any) -> str:
    hints = _type_hints(result_type)
    lines = [
        f"    {field.name}: {_format_annotation(hints.get(field.name, Any))}"
        for field in dataclasses.fields(result_type)
        if field.init
    ]
    return f"{result_type.__name__}:\n" + "\n".join(lines)


def _format_annotation(annotation: Any) -> str:
    return getattr(annotation, "__name__", str(annotation)).replace("typing.", "")


def _has_default(field: Any) -> bool:
    return (
        field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING
    )


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

    declared = [field for field in dataclasses.fields(result_type) if field.init]
    missing = [
        field.name
        for field in declared
        if field.name not in names and not _has_default(field)
    ]
    unexpected = [
        name for name in names if name not in {field.name for field in declared}
    ]
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

    hints = _type_hints(result_type)
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
# Constraint violations
# --------------------------------------------------------------------------


def _integrity_error_to_validation_error(
    exc: psycopg.IntegrityError,
) -> ValidationError | None:
    """The ValidationError the violated constraint describes.

    The same mapping `Model.create()`/`Model.update()` do, found the same way —
    by the constraint name Postgres reports — except that the name is looked up
    across every registered model, because a written statement can write any
    table, not just the one its queryset named.
    """
    constraint_name = exc.diag.constraint_name
    if not constraint_name:
        return None

    for model in models_registry.get_models():
        meta = model._model_meta
        constraint = meta.constraints_by_name.get(
            constraint_name
        ) or meta.foreign_keys_by_constraint_name.get(constraint_name)
        if constraint is None:
            continue
        # No instance: a written statement has rows, not objects. The
        # constraint describes itself without one.
        error = constraint._db_violation_error(None, model)
        if error is None:
            return None
        from plain.exceptions import ValidationError

        return ValidationError(error.update_error_dict({}))

    return None


# --------------------------------------------------------------------------
# The statement
# --------------------------------------------------------------------------


class Written[R]:
    """One written statement, rendered and ready to run.

    Immutable, and it runs at most once: iterate it and the rows are cached,
    the way a queryset caches its result. Call `sql()` again to run it again —
    which matters for writes, where a second iteration must not insert twice.

    It renders when it is constructed, so a bad interpolation fails at the
    call site, and so it can be interpolated into another statement without
    running.
    """

    def __init__(
        self,
        *,
        model: type[Model],
        template: Template,
        result_type: Any = None,
    ) -> None:
        if not isinstance(template, Template):
            # The type checker already says so; this is what an untyped call
            # site gets, and it names the one thing that would be an
            # injection if it were allowed through.
            raise TypeError(
                "sql() takes a t-string. A str -- a literal, an f-string, or "
                f"one built at runtime -- is not one; got "
                f"{type(template).__name__}."
            )

        if result_type is not None and not (
            isinstance(result_type, type) and dataclasses.is_dataclass(result_type)
        ):
            raise TypeError("sql(result_type=...) requires a dataclass.")

        rendered = _render(template)

        # `result_type=` says what a row is, so any `{Model:*}` in the
        # template is just columns -- inside a subquery, most likely. What
        # comes back is checked against the dataclass either way.
        stars = () if result_type is not None else rendered.stars

        # The same model's columns can be expanded more than once -- that is
        # what each branch of a UNION needs -- but two models can't both be
        # the row.
        star_models = dict.fromkeys(star.model for star in stars)
        if len(star_models) > 1:
            names = ", ".join(model.__name__ for model in star_models)
            raise TypeError(
                f"sql() expands {{Model:*}} for more than one model ({names}), "
                "so a row can't be one instance. Select the columns you need "
                "and pass result_type= a dataclass."
            )

        self._model = model
        self._result_type = result_type
        self._stars = stars
        self._instance_model = next(iter(star_models), None)
        self._sql = rendered.sql
        self._bind_sql = rendered.bind_sql
        self._params = rendered.params
        self._prefetch_lookups: tuple[str | Prefetch, ...] = ()
        self._executed = False
        self._row_count = 0
        self._raw_rows: list[tuple[Any, ...]] = []
        self._columns: list[_Column] | None = None
        self._result_cache: list[R] | None = None
        self._count_cache: int | None = None
        self._exists_cache: bool | None = None

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

    def prefetch(self, *lookups: str | Prefetch) -> Self:
        """Load related objects for the instances this statement returns.

        The same as `QuerySet.prefetch()`, and like it this returns a new
        statement — the one it was called on is untouched and still unrun.
        """
        if self._instance_model is None:
            raise TypeError(
                "prefetch() attaches related objects to model instances, and "
                "this statement returns rows. Select {Model:*}, or join the "
                "related table into the statement."
            )
        # The clone carries whatever this statement already ran -- a write
        # must not run a second time just because a prefetch was added -- and
        # only drops the hydrated rows, which is what the prefetch changes.
        clone = copy.copy(self)
        clone._prefetch_lookups = self._prefetch_lookups + lookups
        clone._result_cache = None
        return clone

    # -- running it ---------------------------------------------------------

    @contextmanager
    def _run_statement(self, sql: str, display: str) -> Generator[Any]:
        """Run one statement on the ORM's connection, yielding its cursor.

        The span carries the statement as written — the `%` doubling psycopg
        needs is an artifact of binding, not something to read in a trace — so
        the cursor wrapper's own span is suppressed and this one replaces it.
        """
        connection = get_connection()
        params = list(self._params)
        with _written_cursor(connection) as cursor:
            try:
                with (
                    db_span(
                        connection,
                        display,
                        params=params,
                        row_count_provider=lambda: cursor.rowcount,
                    ),
                    transaction.mark_for_rollback_on_error(),
                    suppress_db_tracing(),
                ):
                    # prepare=False: a named statement is the thing a
                    # transaction-mode pooler can't follow, and
                    # `prepare_threshold` is configurable, so say it outright
                    # rather than relying on the connection's default.
                    cursor.execute(sql, params, prepare=False)
            except psycopg.IntegrityError as exc:
                error = _integrity_error_to_validation_error(exc)
                if error is not None:
                    raise error from exc
                raise
            yield cursor

    def _run(self) -> None:
        """Execute the statement, once, and keep its raw rows."""
        if self._executed:
            return

        with self._run_statement(self._bind_sql, self._sql) as cursor:
            self._row_count = cursor.rowcount
            # `description` is None for a statement with no result at all —
            # a write with no RETURNING clause.
            if cursor.description is not None:
                self._columns = _describe_columns(cursor)
                self._raw_rows = cursor.fetchall()
        self._executed = True

    def _plan_for(self, columns: list[_Column]) -> _Plan:
        """The plan for these result columns, built once per column signature.

        A cached plan is only reused when the statement came back with exactly
        the columns it was built from — same names, same types, same sources.
        A different embedded queryset, or a changed schema, gets a new plan
        instead of the wrong one.
        """
        connection = get_connection()
        plans = _plans.setdefault(connection, {})
        signature = _signature(columns)
        plan = plans.get(signature)
        if (
            plan is not None
            and plan.result_type is self._result_type
            and plan.stars == self._stars
        ):
            return plan

        plan = _build_plan(
            model=self._model,
            stars=self._stars,
            result_type=self._result_type,
            columns=columns,
            connection=connection,
        )
        plans[signature] = plan
        return plan

    def _fetch(self) -> list[R]:
        """The rows, hydrated — instances or `result_type` rows."""
        self._run()
        if self._result_cache is not None:
            return self._result_cache

        if self._columns is None:
            self._result_cache = []
            return self._result_cache

        plan = self._plan_for(self._columns)
        self._result_cache = plan.build(self._raw_rows, get_connection())
        if self._prefetch_lookups:
            prefetch_objects(self._result_cache, *self._prefetch_lookups)
        return self._result_cache

    def _limited(self, limit: int) -> list[R]:
        """The first `limit` rows, without spending the statement's one run.

        Only a read takes this path — `first()` and `get()` on a write go
        through the single execution, because running a write twice is not a
        cheaper way to look at fewer rows.
        """
        if self._executed:
            return self._fetch()[:limit]

        # The statement's own ORDER BY is inside the subquery. Postgres
        # doesn't promise to keep a subquery's ordering, but it does keep it
        # in practice for a plain wrapper like this one -- and `first()` on an
        # unordered statement was already arbitrary.
        sql = _wrap(self._bind_sql, f"LIMIT {limit}")
        display = _wrap(self._sql, f"LIMIT {limit}")
        with self._run_statement(sql, display) as cursor:
            columns = _describe_columns(cursor)
            rows = cursor.fetchall()

        results = self._plan_for(columns).build(rows, get_connection())
        if self._prefetch_lookups:
            prefetch_objects(results, *self._prefetch_lookups)
        return results

    def _scalar(self, sql: str, display: str) -> Any:
        with self._run_statement(sql, display) as cursor:
            row = cursor.fetchone()
        assert row is not None
        return row[0]

    def _reads_rows(self) -> bool:
        """Whether this statement is a read, and so safe to run twice.

        A `SELECT`, a `VALUES`, a parenthesised one, or a `WITH` — a `WITH`
        that holds a write can't be wrapped at all, because Postgres requires
        a data-modifying CTE to be at the top level of its statement and says
        so rather than running it twice.
        """
        return _leading_keyword(self._sql) in ("SELECT", "WITH", "VALUES", "TABLE", "(")

    def _require_a_result(self) -> None:
        """Refuse to answer a question about rows a statement doesn't have.

        A write with no RETURNING clause produces no result at all. Counting
        it would answer 0, which reads like "the UPDATE matched nothing" —
        `execute()` is the question that has an answer.
        """
        self._run()
        if self._columns is None:
            raise TypeError(
                "This statement returns no rows; use execute() for the number "
                "of rows affected."
            )

    def __iter__(self) -> Iterator[R]:
        return iter(self._fetch())

    def __len__(self) -> int:
        self._require_a_result()
        return len(self._fetch())

    def __bool__(self) -> bool:
        self._require_a_result()
        return bool(self._fetch())

    def all(self) -> list[R]:
        """Every row, as a list."""
        return list(self._fetch())

    def first(self) -> R | None:
        """The first row, or None if the statement returned none."""
        rows = self._limited(1) if self._reads_rows() else self._fetch()
        return rows[0] if rows else None

    def get(self) -> R:
        """The one row the statement returned.

        A statement that returns model instances raises that model's
        `DoesNotExist`/`MultipleObjectsReturned`, the same as `QuerySet.get()`.
        A `result_type` statement has no model to raise for, so it raises
        `ValueError`.
        """
        rows = self._limited(2) if self._reads_rows() else self._fetch()
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
        if self._executed or not self._reads_rows():
            # A write counts the rows it returned, from its one execution —
            # wrapping it in a count() would run the write to throw the rows
            # away.
            self._require_a_result()
            return len(self._raw_rows)
        if self._count_cache is None:
            self._count_cache = self._scalar(
                _wrap(self._bind_sql, prefix="SELECT count(*) FROM "),
                _wrap(self._sql, prefix="SELECT count(*) FROM "),
            )
        return self._count_cache

    def exists(self) -> bool:
        """Whether the statement returns any row at all."""
        if self._executed or not self._reads_rows():
            return self.count() > 0  # runs it once, and refuses a resultless one
        if self._count_cache is not None:
            return self._count_cache > 0
        if self._exists_cache is None:
            self._exists_cache = self._scalar(
                _wrap(
                    self._bind_sql, prefix="SELECT EXISTS(SELECT 1 FROM ", suffix=")"
                ),
                _wrap(self._sql, prefix="SELECT EXISTS(SELECT 1 FROM ", suffix=")"),
            )
        return self._exists_cache

    def execute(self) -> int:
        """Run the statement and return how many rows it affected.

        This is the write without a RETURNING clause — the count is what an
        `UPDATE` or `DELETE` has to say. It runs the statement without shaping
        any rows, so a statement with no `result_type` and no `{Model:*}` is
        still runnable this way.
        """
        self._run()
        return self._row_count
