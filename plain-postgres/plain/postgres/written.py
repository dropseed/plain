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

A row is an instance only when `{Model:*}` is the whole select list; every
other shape is a `result_type` dataclass, where a field annotated with a model
class takes that model's expansion — the one in the outer select list, since
an expansion inside a subquery is just columns.

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

    `depth` is how many parentheses were open where it was written. Depth 0 is
    the statement's own select list (each branch of a UNION included); deeper
    is inside a subquery, a CTE or a function call, where the expansion is
    just columns and the outer statement names the ones it wants. `None` means
    the statement's text couldn't be scanned to the end, so nobody knows.
    """

    model: type[Model]
    fields: tuple[Field, ...]
    columns: tuple[str, ...]
    depth: int | None


@dataclasses.dataclass(frozen=True)
class _Rendered:
    sql: str
    bind_sql: str
    params: tuple[Any, ...]
    stars: tuple[_StarExpansion, ...]


class _ParenDepth:
    """How many parentheses are open, scanning the statement as it is written.

    Only the author's own text is scanned. Everything this module renders is
    either parenthesis-free (an identifier, a `%s`) or balanced (an embedded
    queryset or statement, wrapped in its own `(` `)`), so skipping it leaves
    the depth exactly where the author's text put it — and a stray `(` inside
    an embedded query's string literal can't shift it.

    What is skipped, because a parenthesis inside it is text and not
    structure: `'a (quoted) string'` (a doubled `''` is an escaped quote and
    the string goes on), `E'it\\'s ('` — an escape string, where a backslash
    also escapes the character after it — `"a (quoted) identifier"` like a
    plain string, `$$ ( $$` and `$tag$ ( $tag$` dollar-quoted strings (only
    their own tag ends them), `-- ( to end of line`, and `/* ( */` block
    comments, which nest in Postgres.

    The state carries across calls: one string or comment can span the text on
    either side of an interpolation. A statement that ends with the scan still
    inside a string or block comment is one this scan misread — Postgres
    would have refused it — so `unterminated` says its depths can't be
    trusted.
    """

    def __init__(self) -> None:
        self.depth = 0
        self._inside = ""  # "", "'", '"', "--", "/*", or a dollar-quote tag
        self._backslash_escapes = False  # inside an E'...' string
        self._comment_depth = 0

    @property
    def unterminated(self) -> bool:
        # A trailing `-- comment` is a legitimate way for a statement to end.
        return self._inside not in ("", "--")

    def scan(self, text: str) -> None:
        index = 0
        while index < len(text):
            if self._inside == "":
                index = self._scan_sql(text, index)
            elif self._inside in ("'", '"'):
                index = self._scan_quoted(text, index)
            elif self._inside == "--":
                if text[index] == "\n":
                    self._inside = ""
                index += 1
            elif self._inside == "/*":
                index = self._scan_comment(text, index)
            else:
                index = self._scan_dollar_quoted(text, index)

    def _scan_sql(self, text: str, index: int) -> int:
        char = text[index]
        if char == "(":
            self.depth += 1
        elif char == ")":
            # A statement can't have more `)` than `(`, but a fragment handed
            # in on its own can -- never go below the outer select list.
            self.depth = max(0, self.depth - 1)
        elif char == "'":
            self._inside = char
            self._backslash_escapes = _opens_escape_string(text, index)
        elif char == '"':
            self._inside = char
            self._backslash_escapes = False
        elif text.startswith("--", index):
            self._inside = "--"
            return index + 2
        elif text.startswith("/*", index):
            self._inside = "/*"
            self._comment_depth = 1
            return index + 2
        elif (tag := _dollar_quote_tag(text, index)) is not None:
            self._inside = tag
            return index + len(tag)
        return index + 1

    def _scan_quoted(self, text: str, index: int) -> int:
        quote = self._inside
        if self._backslash_escapes and text[index] == "\\":
            return index + 2  # E'...': the next character is taken literally
        if not text.startswith(quote, index):
            return index + 1
        if text.startswith(quote * 2, index):
            return index + 2  # an escaped quote: the literal goes on
        self._inside = ""
        return index + 1

    def _scan_comment(self, text: str, index: int) -> int:
        if text.startswith("/*", index):
            self._comment_depth += 1
            return index + 2
        if text.startswith("*/", index):
            self._comment_depth -= 1
            if self._comment_depth == 0:
                self._inside = ""
            return index + 2
        return index + 1

    def _scan_dollar_quoted(self, text: str, index: int) -> int:
        if text.startswith(self._inside, index):
            tag_length = len(self._inside)
            self._inside = ""
            return index + tag_length
        return index + 1


def _follows_identifier(text: str, index: int) -> bool:
    """Whether the character before `index` is part of a word."""
    return index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_")


def _opens_escape_string(text: str, index: int) -> bool:
    """Whether the `'` at `index` opens an `E'...'` escape string.

    The `E` has to stand alone: in `TYPE'x'` it ends a word, and the string
    is an ordinary one.
    """
    return (
        index > 0
        and text[index - 1] in "Ee"
        and not _follows_identifier(text, index - 1)
    )


def _dollar_quote_tag(text: str, index: int) -> str | None:
    """The `$$` or `$tag$` that opens a dollar-quoted string at `index`.

    A `$` inside a word is part of an identifier (`a$b$` is one), never a
    quote.
    """
    if text[index] != "$" or _follows_identifier(text, index):
        return None
    end = text.find("$", index + 1)
    if end == -1:
        return None
    tag = text[index + 1 : end]
    if tag and not tag.isidentifier():
        return None
    return text[index : end + 1]


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
        self.paren_depth = _ParenDepth()

    def author(self, text: str) -> None:
        """Text the author wrote: template literals and fragments."""
        self.bind.append(text.replace("%", "%%"))
        self.display.append(text)
        self.paren_depth.scan(text)

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

    if sql.paren_depth.unterminated:
        # The scan ended inside a string or comment Postgres would have seen
        # closed, so it misread something and no depth it recorded can be
        # trusted. An unknown depth is never the outer select list.
        stars = [dataclasses.replace(star, depth=None) for star in stars]

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


def _brace_lookalike_error(expression: str) -> str | None:
    """The message for braces that were meant to stay braces, if these were.

    `'^\\d{2}$'` is a regex whose braces weren't doubled, and Python read
    `{2}` as an interpolation of the int 2. Nothing downstream can tell that
    from a parameter, so the source text between the braces answers it — but
    only for the two shapes a forgotten brace actually makes: a bare integer
    (a quantifier) and a comma-separated run of literals (an array literal,
    a regex range). Every other literal is left alone to bind, because
    `{None}`, `{"active"}` and `{True}` are values someone meant.
    """
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return None

    doubled = f"{{{{{expression}}}}}"

    # `type(...) is int` rather than isinstance: True is an int, and a bool
    # is a value to bind.
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return (
            f"{{{expression}}} interpolates the number {node.value} as a bound "
            "parameter. Write the number into the SQL, or — if this was meant "
            "to be a literal brace, a regex quantifier like \\d{2} or an array "
            f"literal — write {doubled}."
        )

    # `'{1,2,3}'` parses as a tuple. A set can only come from braces the
    # author typed on purpose, but psycopg can't adapt one either way.
    if isinstance(node, ast.Tuple | ast.Set) and all(
        isinstance(element, ast.Constant) for element in node.elts
    ):
        kind = type(node).__name__.lower()
        return (
            f"{{{expression}}} interpolates a {kind} of literals as a bound "
            "parameter. Write them into the SQL, or — if this was meant to be "
            "a literal brace, an array literal or a regex range — write "
            f"{doubled}."
        )

    return None


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

    if (lookalike := _brace_lookalike_error(written)) is not None:
        raise ValueError(lookalike)

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
            "is `:*`, which expands to every column of it."
        )

    fields = tuple(model._model_meta.fields)
    stars.append(
        _StarExpansion(
            model=model,
            fields=fields,
            columns=tuple(field.column for field in fields),
            depth=sql.paren_depth.depth,
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
class _ModelField:
    """A `result_type` field that a `{Model:*}` expansion fills.

    `start` is where the expansion's run of columns begins in the result, and
    `pk_position` is the primary key's place inside that run — the one column
    a real row can never have NULL in, so an all-NULL run (the outer side of a
    join that matched nothing) is recognised by it alone.
    """

    name: str
    star: _StarExpansion
    start: int
    pk_position: int
    allow_null: bool


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
    model_fields: tuple[_ModelField, ...]
    named_columns: tuple[tuple[int, str], ...]
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
            return [self._hydrate(self.star, self.star_start, row) for row in converted]

        assert self.result_type is not None
        return [self._row(row) for row in converted]

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

    def _row(self, row: Sequence[Any]) -> Any:
        """One `result_type` row: columns by name, expansions by model class."""
        values = {name: row[position] for position, name in self.named_columns}
        for model_field in self.model_fields:
            values[model_field.name] = self._model_value(model_field, row)
        return self.result_type(**values)

    def _model_value(
        self, model_field: _ModelField, row: Sequence[Any]
    ) -> Model | None:
        model = model_field.star.model
        if row[model_field.start + model_field.pk_position] is None:
            # The expansion came back all NULL, which only an outer join that
            # matched nothing does -- a real row always has a primary key.
            if model_field.allow_null:
                return None
            raise TypeError(
                f"{self.result_type.__name__}.{model_field.name} came back with "
                f"every {model.__name__} column NULL -- the outer side of a "
                f"join that matched nothing. Annotate it "
                f"`{model.__name__} | None` to get None there."
            )
        return self._hydrate(model_field.star, model_field.start, row)

    def _hydrate(self, star: _StarExpansion, start: int, row: Sequence[Any]) -> Model:
        """The instance one `{Model:*}` expansion's run of columns describes."""
        return star.model.from_db(
            [field.name for field in star.fields],
            list(row[start : start + len(star.fields)]),
        )


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

    if result_type is None:
        star, star_start = _instance_star(
            model=model, stars=stars, names=names, fields=fields
        )
        return _Plan(
            signature=_signature(columns),
            names=names,
            converters=converters,
            decryptable=decryptable,
            star=star,
            star_start=star_start,
            model_fields=(),
            named_columns=(),
            stars=stars,
            result_type=None,
        )

    # Only an expansion in the outer select list puts its columns in the
    # result; a deeper one is just columns of a subquery, whatever the outer
    # statement then names them.
    outer = tuple(star for star in stars if star.depth == 0)
    starts = _allocate_star_runs(names, fields, outer)

    model_fields = _model_fields_for(
        result_type=result_type,
        stars=stars,
        outer=outer,
        starts=starts,
        names=names,
    )
    _refuse_an_unmapped_expansion(
        result_type=result_type,
        outer=outer,
        starts=starts,
        model_fields=model_fields,
    )
    expanded = {
        position
        for model_field in model_fields
        for position in range(
            model_field.start, model_field.start + len(model_field.star.fields)
        )
    }
    named_columns = tuple(
        (position, name)
        for position, name in enumerate(names)
        if position not in expanded
    )
    _check_result_type(
        result_type=result_type,
        names=names,
        model_fields=model_fields,
        named_columns=named_columns,
        columns=columns,
        fields=fields,
        connection=connection,
    )
    return _Plan(
        signature=_signature(columns),
        names=names,
        converters=converters,
        decryptable=decryptable,
        star=None,
        star_start=0,
        model_fields=model_fields,
        named_columns=named_columns,
        stars=stars,
        result_type=result_type,
    )


def _instance_star(
    *,
    model: type[Model],
    stars: tuple[_StarExpansion, ...],
    names: tuple[str, ...],
    fields: list[Field | None],
) -> tuple[_StarExpansion, int]:
    """The expansion a row *is*, for a statement with no `result_type`.

    An instance is always complete and carries only its own columns, so this
    is the one shape a statement can have without declaring it: `{Model:*}`
    and nothing else. One more column and the row has a shape of its own.
    """
    if not stars:
        raise TypeError(
            f"This statement returns columns ({', '.join(names)}) and nothing "
            f"says what a row is. Select {{{model.__name__}:*}} to get "
            "instances, or pass result_type= a dataclass."
        )

    star = _instance_stars(stars)[0]
    start = _locate_star(names, fields, star, claimed=[])
    if start is None:
        raise TypeError(
            f"This statement returns ({', '.join(names)}), which doesn't "
            f"contain {star.model.__name__}'s columns "
            f"({', '.join(star.columns)}) in order. If the "
            f"{{{star.model.__name__}:*}} is inside a subquery, select the "
            "columns you want in the outer statement and pass result_type= a "
            "dataclass; otherwise something renamed them, and a "
            f"{{{star.model.__name__}:*}} row can't be aliased."
        )

    extra = [
        name
        for position, name in enumerate(names)
        if not start <= position < start + len(star.fields)
    ]
    if extra:
        raise TypeError(
            f"This statement selects {{{star.model.__name__}:*}} and other "
            f"columns ({', '.join(extra)}), so a row is not a "
            f"{star.model.__name__} -- it has a shape of its own. Declare that "
            f"shape: a dataclass with a `{star.model.__name__}` field for the "
            "instance and a field per extra column, passed as result_type=."
        )
    return star, start


def _instance_stars(stars: tuple[_StarExpansion, ...]) -> tuple[_StarExpansion, ...]:
    """The expansions that could be the row of a statement with no `result_type`.

    The outer select list first — that is where a row is declared. With no
    expansion there, a statement that passes a subquery's `{Model:*}` straight
    through (`SELECT * FROM (SELECT {Model:*} ...) sub`) still means those
    instances and nothing else, so the deeper ones are read as a fallback.
    """
    outer = tuple(star for star in stars if star.depth == 0)
    return outer or stars


def _allocate_star_runs(
    names: tuple[str, ...],
    fields: list[Field | None],
    stars: tuple[_StarExpansion, ...],
) -> list[int | None]:
    """Where each expansion's run of columns is, in the order they were written.

    Two expansions never read the same columns, so each takes the first run
    left to it and the ones behind it have to look elsewhere. The exception is
    the same model expanded in each branch of a UNION: the branches collapse
    onto one set of result columns, so the second takes the very run the first
    did.
    """
    starts: list[int | None] = []
    claimed: list[tuple[int, int, type[Model]]] = []
    for star in stars:
        start = _locate_star(names, fields, star, claimed=claimed)
        starts.append(start)
        if start is not None:
            run = (start, len(star.columns), star.model)
            if run not in claimed:
                claimed.append(run)
    return starts


def _run_is_unclaimed(
    start: int,
    width: int,
    model: type[Model],
    claimed: list[tuple[int, int, type[Model]]],
) -> bool:
    """Whether this run of columns is still free for this expansion to take."""
    for claimed_start, claimed_width, claimed_model in claimed:
        if (start, width, model) == (claimed_start, claimed_width, claimed_model):
            continue  # the same model's run in another UNION branch
        if start < claimed_start + claimed_width and claimed_start < start + width:
            return False
    return True


def _star_runs(names: tuple[str, ...], star: _StarExpansion) -> list[int]:
    """Every position where this expansion's run of columns could start.

    The expansion emitted the model's columns, in declared order, as one run —
    so a run of result columns with those names is where it could be. Reading
    it back by name means the instance's fields are the ones the template asked
    for, not whichever columns the catalog happens to trace to this model: a
    self-join, a UNION branch, or another table with the same column names
    can't shift them.
    """
    width = len(star.columns)
    return [
        start
        for start in range(len(names) - width + 1)
        if tuple(names[start : start + width]) == star.columns
    ]


def _locate_star(
    names: tuple[str, ...],
    fields: list[Field | None],
    star: _StarExpansion,
    *,
    claimed: list[tuple[int, int, type[Model]]],
) -> int | None:
    """Where `{Model:*}`'s columns start in the result, or None if they aren't there.

    Not there means the expansion's columns never reached the outer select
    list under their own names — it is inside a subquery, or another
    expansion already took the only run they match.
    """
    width = len(star.columns)
    candidates = [
        start
        for start in _star_runs(names, star)
        if _run_is_unclaimed(start, width, star.model, claimed)
    ]
    if not candidates:
        return None

    if len(candidates) == 1:
        start = candidates[0]
        # Column names alone are weak evidence: every model's columns start
        # with `id`, so one model's list is often a prefix of another's. Every
        # column that kept its source has to be this expansion's own column in
        # that place; one that traces anywhere else means this run belongs to
        # something else. (A UNION keeps no sources, so names are all it has.)
        traced = [
            (offset, fields[start + offset])
            for offset in range(width)
            if fields[start + offset] is not None
        ]
        if not all(field is star.fields[offset] for offset, field in traced):
            return None
        return start

    # Two runs of columns have those names. Provenance breaks the tie when it
    # survived; when it didn't, the statement is genuinely ambiguous.
    confirmed = [
        start
        for start in candidates
        if all(fields[start + offset] is star.fields[offset] for offset in range(width))
    ]
    if len(confirmed) != 1:
        raise TypeError(
            f"This statement returns {star.model.__name__}'s columns "
            f"({', '.join(star.columns)}) more than once, so which run is "
            f"the {star.model.__name__} is ambiguous. Alias the other one's "
            "columns."
        )
    return confirmed[0]


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


def _model_annotation(annotation: Any) -> tuple[type[Model], bool] | None:
    """The model a `result_type` field is annotated with, and whether it allows None.

    `widget: Widget` is `(Widget, False)` and `widget: Widget | None` is
    `(Widget, True)`. Anything else is an ordinary column field.
    """
    allow_null = False
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = typing.get_args(annotation)
        named = [arg for arg in args if arg is not type(None)]
        allow_null = len(named) < len(args)
        if len(named) != 1:
            return None  # a real union: nothing single to fill
        annotation = named[0]

    if isinstance(annotation, type) and issubclass(annotation, Model):
        return annotation, allow_null
    return None


def _union_models(annotation: Any) -> list[type[Model]]:
    """The model classes a union annotation names, `None` aside."""
    if typing.get_origin(annotation) not in (typing.Union, types.UnionType):
        return []
    return [
        arg
        for arg in typing.get_args(annotation)
        if isinstance(arg, type) and issubclass(arg, Model)
    ]


def _model_fields_for(
    *,
    result_type: Any,
    stars: tuple[_StarExpansion, ...],
    outer: tuple[_StarExpansion, ...],
    starts: list[int | None],
    names: tuple[str, ...],
) -> tuple[_ModelField, ...]:
    """Pair each model-annotated field of `result_type` with its expansion.

    The annotation names the model and an expansion is *of* a model, so the two
    find each other by model class. There is nothing else to match on, which is
    why one model can fill one field, from one run of columns.
    """
    hints = _type_hints(result_type)
    annotated: list[tuple[str, type[Model], bool]] = []
    for field in dataclasses.fields(result_type):
        if not field.init:
            continue
        model_annotation = _model_annotation(hints.get(field.name))
        if model_annotation is not None:
            model, allow_null = model_annotation
            annotated.append((field.name, model, allow_null))
            continue
        union = _union_models(hints.get(field.name))
        if len(union) > 1:
            raise TypeError(
                f"{result_type.__name__}.{field.name} is annotated "
                f"{' | '.join(model.__name__ for model in union)}. A row has "
                "one shape, so a model field names one model -- the one this "
                "statement expands -- or you select the columns you want "
                "instead."
            )

    fields_by_model: dict[type[Model], list[str]] = {}
    for name, model, _ in annotated:
        fields_by_model.setdefault(model, []).append(name)
    for model, field_names in fields_by_model.items():
        if len(field_names) > 1:
            raise TypeError(
                f"{result_type.__name__} declares more than one "
                f"{model.__name__} field ({', '.join(field_names)}), and one "
                f"{{{model.__name__}:*}} expansion can only fill one of them. A "
                "self-join needs aliases an expansion can't give -- select the "
                "columns you want instead."
            )

    if annotated:
        _refuse_models_sharing_a_run(outer=outer, starts=starts)

    model_fields = []
    for name, model, allow_null in annotated:
        if not any(star.model is model for star in stars):
            raise TypeError(
                f"{result_type.__name__}.{name} is a {model.__name__}, and "
                f"nothing in this statement selects {{{model.__name__}:*}} to "
                f"fill it. Declare {{{model.__name__}:*}} in the select list, or "
                "drop the field."
            )

        located = [
            (star, start)
            for star, start in zip(outer, starts, strict=True)
            if star.model is model and start is not None
        ]
        if not located and any(
            star.model is model and star.depth is None for star in stars
        ):
            raise TypeError(
                f"{result_type.__name__}.{name} is a {model.__name__}, but this "
                "statement's SQL couldn't be scanned to the end -- it reads as "
                "ending inside an unterminated string or comment -- so there is "
                f"no telling whether its {{{model.__name__}:*}} is in the outer "
                "select list. Check the quoting (an E'...' string, a $tag$ "
                "string, a /* comment */), or select the columns you want "
                "instead."
            )
        if not located:
            # Either every expansion of this model is inside a subquery, or
            # the outer one's columns never arrived under their own names.
            raise TypeError(
                f"{result_type.__name__}.{name} is a {model.__name__}, but this "
                f"statement returns ({', '.join(names)}), which doesn't contain "
                f"{model.__name__}'s columns in order. Select "
                f"{{{model.__name__}:*}} in the outer select list -- an "
                "expansion inside a subquery is just columns, and a "
                f"{{{model.__name__}:*}} row can't be aliased."
            )

        runs = sorted({start for _, start in located})
        if len(runs) > 1:
            positions = ", ".join(str(start) for start in runs)
            raise TypeError(
                f"This statement expands {{{model.__name__}:*}} into two "
                f"different runs of columns (starting at {positions}), and "
                f"{result_type.__name__}.{name} can only be one of them. Select "
                "the columns you want instead."
            )

        star, start = located[0]
        model_fields.append(
            _ModelField(
                name=name,
                star=star,
                start=start,
                pk_position=_pk_position(star),
                allow_null=allow_null,
            )
        )

    return tuple(model_fields)


def _refuse_models_sharing_a_run(
    *,
    outer: tuple[_StarExpansion, ...],
    starts: list[int | None],
) -> None:
    """Two models expanded onto one run of columns can't fill a model field.

    An outer expansion that found no run of its own is in a later branch of a
    UNION: its rows arrive in the same columns as the first branch's, by
    position. When it is a different model from the one that did find the
    run, a row can't say which model it is — hydrating it as the first would
    turn the other's rows into that model's instances.
    """
    placed = [
        star for star, start in zip(outer, starts, strict=True) if start is not None
    ]
    unplaced = [
        star for star, start in zip(outer, starts, strict=True) if start is None
    ]
    for other in unplaced:
        for star in placed:
            if star.model is other.model:
                continue
            raise TypeError(
                f"This statement expands {{{star.model.__name__}:*}} and "
                f"{{{other.model.__name__}:*}} onto the same run of result "
                "columns -- the branches of a UNION share one -- so a row "
                "can't say which model it is. Give each model its own "
                "statement, or select the columns you want and map them by "
                "name."
            )


def _pk_position(star: _StarExpansion) -> int:
    """Where the primary key sits inside the expansion's run of columns."""
    return next(
        position for position, field in enumerate(star.fields) if field.primary_key
    )


def _refuse_an_unmapped_expansion(
    *,
    result_type: Any,
    outer: tuple[_StarExpansion, ...],
    starts: list[int | None],
    model_fields: tuple[_ModelField, ...],
) -> None:
    """A `{Model:*}` whose columns the dataclass has no room for.

    An expansion no model field claimed is columns like any others: they map
    onto same-named fields, which is what `SELECT {Model:*}` under a dataclass
    of its columns means and what a UNION of two star selects needs. When some
    of them have no field at all, the expansion is what the dataclass is
    missing, and saying so is more use than naming its columns one by one.
    """
    claimed = {model_field.star.model for model_field in model_fields}
    declared = {field.name for field in dataclasses.fields(result_type) if field.init}
    for star, start in zip(outer, starts, strict=True):
        if star.model in claimed or start is None:
            continue
        unmapped = [column for column in star.columns if column not in declared]
        if not unmapped:
            continue
        raise TypeError(
            f"This statement selects {{{star.model.__name__}:*}} and "
            f"{result_type.__name__} has no field for "
            f"{', '.join(unmapped)}. Declare "
            f"`{star.model.__name__.lower()}: {star.model.__name__}` to take "
            "the whole expansion, or select the columns you want instead."
        )


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
    *,
    result_type: Any,
    names: tuple[str, ...],
    model_fields: tuple[_ModelField, ...],
    named_columns: tuple[tuple[int, str], ...],
    columns: list[_Column],
    fields: list[Field | None],
    connection: DatabaseConnection,
) -> None:
    """Check the result columns against the dataclass, by name then by type.

    The columns an expansion filled are already spoken for — they went into a
    model-annotated field whole — so what is left is matched by name.
    """
    by_name = tuple(name for _, name in named_columns)
    if len(set(by_name)) != len(by_name):
        raise TypeError(
            f"This statement returns duplicate column names ({', '.join(by_name)}), "
            f"and {result_type.__name__} maps columns by name. Alias them apart."
        )

    expanded = {model_field.name for model_field in model_fields}
    declared = [
        field
        for field in dataclasses.fields(result_type)
        if field.init and field.name not in expanded
    ]
    missing = [
        field.name
        for field in declared
        if field.name not in by_name and not _has_default(field)
    ]
    unexpected = [
        name for name in by_name if name not in {field.name for field in declared}
    ]
    if missing or unexpected:
        problems = []
        if missing:
            problems.append(f"no column for {', '.join(missing)}")
        if unexpected:
            problems.append(f"no field for column {', '.join(unexpected)}")
        # Every column the statement returned, and which of them a model field
        # already took whole — otherwise a statement whose expansion took
        # everything reads as having returned nothing.
        taken = "".join(
            f" ({model_field.name} took "
            f"{', '.join(names[model_field.start : model_field.start + len(model_field.star.columns)])})"
            for model_field in model_fields
        )
        raise TypeError(
            f"This statement doesn't match {result_type.__name__} — "
            f"{'; '.join(problems)}. It returned {', '.join(names)}{taken}, "
            f"and the dataclass declares\n{_describe_result_type(result_type)}"
        )

    hints = _type_hints(result_type)
    for position, name in named_columns:
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

        # With a `result_type` each expansion fills the field annotated with
        # its model, so several models can be starred -- and a row is the
        # dataclass, never an instance. Without one, the row *is* the
        # instance: the same model's columns can be expanded more than once
        # (that is what each branch of a UNION needs), but two models can't
        # both be the row.
        instance_model = None
        if result_type is None and rendered.stars:
            star_models = dict.fromkeys(
                star.model for star in _instance_stars(rendered.stars)
            )
            if len(star_models) > 1:
                names = ", ".join(model.__name__ for model in star_models)
                raise TypeError(
                    f"sql() expands {{Model:*}} for more than one model "
                    f"({names}), so a row can't be one instance. Pass "
                    "result_type= a dataclass with a field for each model."
                )
            instance_model = next(iter(star_models), None)

        self._model = model
        self._result_type = result_type
        self._stars = rendered.stars
        self._instance_model = instance_model
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
