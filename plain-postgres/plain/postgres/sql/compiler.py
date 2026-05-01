from __future__ import annotations

import collections
import json
import re
from collections.abc import Generator, Iterable, Sequence
from functools import cached_property, partial
from itertools import chain
from typing import TYPE_CHECKING, Any, Protocol, cast

from plain.postgres.constants import LOOKUP_SEP
from plain.postgres.dialect import (
    PK_DEFAULT_VALUE,
    bulk_insert_sql,
    distinct_sql,
    explain_query_prefix,
    for_update_sql,
    limit_offset_sql,
    on_conflict_suffix_sql,
    quote_name,
    return_insert_columns,
)
from plain.postgres.exceptions import EmptyResultSet, FieldError, FullResultSet
from plain.postgres.expressions import (
    F,
    OrderBy,
    RawSQL,
    Ref,
    ResolvableExpression,
    Value,
)
from plain.postgres.fields import DATABASE_DEFAULT
from plain.postgres.fields.related import RelatedField
from plain.postgres.functions import Cast, Random
from plain.postgres.lookups import Lookup
from plain.postgres.meta import Meta
from plain.postgres.query_utils import select_related_descend
from plain.postgres.sql.constants import (
    CURSOR,
    MULTI,
    NO_RESULTS,
    ORDER_DIR,
    SINGLE,
)
from plain.postgres.sql.query import Query, get_order_dir
from plain.postgres.transaction import TransactionManagementError
from plain.utils.hashable import make_hashable
from plain.utils.regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.expressions import BaseExpression
    from plain.postgres.sql.query import AggregateQuery, InsertQuery

# Type aliases for SQL compilation results
SqlParams = tuple[Any, ...]
SqlWithParams = tuple[str, SqlParams]


class SQLCompilable(Protocol):
    """Protocol for objects that can be compiled to SQL."""

    def as_sql(
        self, compiler: SQLCompiler, connection: DatabaseConnection
    ) -> tuple[str, Sequence[Any]]:
        """Return SQL string and parameters for this object."""
        ...


class PositionRef(Ref):
    def __init__(self, ordinal: int, refs: str, source: Any):
        self.ordinal = ordinal
        super().__init__(refs, source)

    def as_sql(
        self, compiler: SQLCompiler, connection: DatabaseConnection
    ) -> tuple[str, list[Any]]:
        return str(self.ordinal), []


def get_converters(
    expressions: Iterable[Any], connection: DatabaseConnection
) -> dict[int, tuple[list[Any], Any]]:
    converters = {}
    for i, expression in enumerate(expressions):
        if expression:
            field_converters = expression.get_db_converters(connection)
            if field_converters:
                converters[i] = (field_converters, expression)
    return converters


def apply_converters(
    rows: Iterable, converters: dict, connection: DatabaseConnection
) -> Generator[list]:
    converters_list = list(converters.items())
    for row in map(list, rows):
        for pos, (convs, expression) in converters_list:
            value = row[pos]
            for converter in convs:
                value = converter(value, expression, connection)
            row[pos] = value
        yield row


class SQLCompiler:
    # Multiline ordering SQL clause may appear from RawSQL.
    ordering_parts = _lazy_re_compile(
        r"^(.*)\s(?:ASC|DESC).*",
        re.MULTILINE | re.DOTALL,
    )

    def __init__(
        self, query: Query, connection: DatabaseConnection, elide_empty: bool = True
    ):
        self.query = query
        self.connection = connection
        # Some queries, e.g. coalesced aggregation, need to be executed even if
        # they would return an empty result set.
        self.elide_empty = elide_empty
        self.quote_cache: dict[str, str] = {"*": "*"}
        # The select, klass_info, and annotations are needed by QuerySet.iterator()
        # these are set as a side-effect of executing the query. Note that we calculate
        # separately a list of extra select columns needed for grammatical correctness
        # of the query, but these columns are not included in self.select.
        self.select: list[tuple[Any, SqlWithParams, str | None]] | None = None
        self.annotation_col_map: dict[str, int] | None = None
        self.klass_info: dict[str, Any] | None = None
        self._meta_ordering: list[str] | None = None

    def __repr__(self) -> str:
        model_name = self.query.model.__qualname__ if self.query.model else "None"
        return (
            f"<{self.__class__.__qualname__} "
            f"model={model_name} "
            f"connection={self.connection!r}>"
        )

    def setup_query(self, with_col_aliases: bool = False) -> None:
        if all(self.query.alias_refcount[a] == 0 for a in self.query.alias_map):
            self.query.get_initial_alias()
        self.select, self.klass_info, self.annotation_col_map = self.get_select(
            with_col_aliases=with_col_aliases,
        )
        self.col_count = len(self.select)

    def pre_sql_setup(
        self, with_col_aliases: bool = False
    ) -> tuple[list[Any], list[Any], list[SqlWithParams]] | None:
        """
        Do any necessary class setup immediately prior to producing SQL. This
        is for things that can't necessarily be done in __init__ because we
        might not have all the pieces in place at that time.
        """
        self.setup_query(with_col_aliases=with_col_aliases)
        assert self.select is not None  # Set by setup_query()
        order_by = self.get_order_by()
        self.where, self.having, self.qualify = self.query.where.split_having_qualify(
            must_group_by=self.query.group_by is not None
        )
        extra_select = self.get_extra_select(order_by, self.select)
        self.has_extra_select = bool(extra_select)
        group_by = self.get_group_by(self.select + extra_select, order_by)
        return extra_select, order_by, group_by

    def get_group_by(
        self, select: list[Any], order_by: list[Any]
    ) -> list[SqlWithParams]:
        """
        Return a list of 2-tuples of form (sql, params).

        The logic of what exactly the GROUP BY clause contains is hard
        to describe in other words than "if it passes the test suite,
        then it is correct".
        """
        # Some examples:
        #     SomeModel.query.annotate(Count('somecol'))
        #     GROUP BY: all fields of the model
        #
        #    SomeModel.query.values('name').annotate(Count('somecol'))
        #    GROUP BY: name
        #
        #    SomeModel.query.annotate(Count('somecol')).values('name')
        #    GROUP BY: all cols of the model
        #
        #    SomeModel.query.values('name', 'id')
        #    .annotate(Count('somecol')).values('id')
        #    GROUP BY: name, id
        #
        #    SomeModel.query.values('name').annotate(Count('somecol')).values('id')
        #    GROUP BY: name, id
        #
        # In fact, the self.query.group_by is the minimal set to GROUP BY. It
        # can't be ever restricted to a smaller set, but additional columns in
        # HAVING, ORDER BY, and SELECT clauses are added to it. Unfortunately
        # the end result is that it is impossible to force the query to have
        # a chosen GROUP BY clause - you can almost do this by using the form:
        #     .values(*wanted_cols).annotate(AnAggregate())
        # but any later annotations, extra selects, values calls that
        # refer some column outside of the wanted_cols, order_by, or even
        # filter calls can alter the GROUP BY clause.

        # The query.group_by is either None (no GROUP BY at all), True
        # (group by select fields), or a list of expressions to be added
        # to the group by.
        if self.query.group_by is None:
            return []
        expressions = []
        group_by_refs = set()
        if self.query.group_by is not True:
            # If the group by is set to a list (by .values() call most likely),
            # then we need to add everything in it to the GROUP BY clause.
            # Backwards compatibility hack for setting query.group_by. Remove
            # when we have public API way of forcing the GROUP BY clause.
            # Converts string references to expressions.
            for expr in self.query.group_by:
                if not hasattr(expr, "as_sql"):
                    expr = self.query.resolve_ref(expr)
                if isinstance(expr, Ref):
                    if expr.refs not in group_by_refs:
                        group_by_refs.add(expr.refs)
                        expressions.append(expr.source)
                else:
                    expressions.append(expr)
        # Note that even if the group_by is set, it is only the minimal
        # set to group by. So, we need to add cols in select, order_by, and
        # having into the select in any case.
        selected_expr_positions = {}
        for ordinal, (expr, _, alias) in enumerate(select, start=1):
            if alias:
                selected_expr_positions[expr] = ordinal
            # Skip members of the select clause that are already explicitly
            # grouped against.
            if alias in group_by_refs:
                continue
            expressions.extend(expr.get_group_by_cols())
        if not self._meta_ordering:
            for expr, (sql, params, is_ref) in order_by:
                # Skip references to the SELECT clause, as all expressions in
                # the SELECT clause are already part of the GROUP BY.
                if not is_ref:
                    expressions.extend(expr.get_group_by_cols())
        having_group_by = self.having.get_group_by_cols() if self.having else []
        for expr in having_group_by:
            expressions.append(expr)
        result = []
        seen = set()
        expressions = self.collapse_group_by(expressions, having_group_by)

        for expr in expressions:
            try:
                sql, params = self.compile(expr)
            except (EmptyResultSet, FullResultSet):
                continue
            # Use select index for GROUP BY when possible
            if (position := selected_expr_positions.get(expr)) is not None:
                sql, params = str(position), ()
            else:
                sql, params = expr.select_format(self, sql, params)
            params_hash = make_hashable(params)
            if (sql, params_hash) not in seen:
                result.append((sql, params))
                seen.add((sql, params_hash))
        return result

    def collapse_group_by(self, expressions: list[Any], having: list[Any]) -> list[Any]:
        # Use group by functional dependence reduction:
        # expressions can be reduced to the set of selected table
        # primary keys as all other columns are functionally dependent on them.
        # Filter out all expressions associated with a table's primary key
        # present in the grouped columns. This is done by identifying all
        # tables that have their primary key included in the grouped
        # columns and removing non-primary key columns referring to them.
        pks = {
            expr
            for expr in expressions
            if hasattr(expr, "target") and expr.target.primary_key
        }
        aliases = {expr.alias for expr in pks}
        return [
            expr
            for expr in expressions
            if expr in pks
            or expr in having
            or getattr(expr, "alias", None) not in aliases
        ]

    def get_select(
        self, with_col_aliases: bool = False
    ) -> tuple[
        list[tuple[Any, SqlWithParams, str | None]],
        dict[str, Any] | None,
        dict[str, int],
    ]:
        """
        Return three values:
        - a list of 3-tuples of (expression, (sql, params), alias)
        - a klass_info structure,
        - a dictionary of annotations

        The (sql, params) is what the expression will produce, and alias is the
        "AS alias" for the column (possibly None).

        The klass_info structure contains the following information:
        - The base model of the query.
        - Which columns for that model are present in the query (by
          position of the select clause).
        - related_klass_infos: [f, klass_info] to descent into

        The annotations is a dictionary of {'attname': column position} values.
        """
        select = []
        klass_info = None
        annotations = {}
        select_idx = 0
        for alias, (sql, params) in self.query.extra_select.items():
            annotations[alias] = select_idx
            select.append((RawSQL(sql, params), alias))
            select_idx += 1
        assert not (self.query.select and self.query.default_cols)
        select_mask = self.query.get_select_mask()
        if self.query.default_cols:
            cols = self.get_default_columns(select_mask)
        else:
            # self.query.select is a special case. These columns never go to
            # any model.
            cols = self.query.select
        if cols:
            select_list = []
            for col in cols:
                select_list.append(select_idx)
                select.append((col, None))
                select_idx += 1
            klass_info = {
                "model": self.query.model,
                "select_fields": select_list,
            }
        for alias, annotation in self.query.annotation_select.items():
            annotations[alias] = select_idx
            select.append((annotation, alias))
            select_idx += 1

        if self.query.select_related:
            related_klass_infos = self.get_related_selections(select, select_mask)
            if klass_info is not None:
                klass_info["related_klass_infos"] = related_klass_infos

        ret = []
        col_idx = 1
        for col, alias in select:
            try:
                sql, params = self.compile(col)
            except EmptyResultSet:
                empty_result_set_value = getattr(
                    col, "empty_result_set_value", NotImplemented
                )
                if empty_result_set_value is NotImplemented:
                    # Select a predicate that's always False.
                    sql, params = "0", ()
                else:
                    sql, params = self.compile(Value(empty_result_set_value))
            except FullResultSet:
                sql, params = self.compile(Value(True))
            else:
                sql, params = col.select_format(self, sql, params)
            if alias is None and with_col_aliases:
                alias = f"col{col_idx}"
                col_idx += 1
            ret.append((col, (sql, params), alias))
        return ret, klass_info, annotations

    def _order_by_pairs(self) -> Generator[tuple[OrderBy, bool]]:
        if self.query.extra_order_by:
            ordering = self.query.extra_order_by
        elif not self.query.default_ordering:
            ordering = self.query.order_by
        elif self.query.order_by:
            ordering = self.query.order_by
        elif (
            self.query.model
            and (options := self.query.model.model_options)
            and options.ordering
        ):
            ordering = options.ordering
            self._meta_ordering = list(ordering)
        else:
            ordering = []
        if self.query.standard_ordering:
            default_order, _ = ORDER_DIR["ASC"]
        else:
            default_order, _ = ORDER_DIR["DESC"]

        selected_exprs = {}
        if select := self.select:
            for ordinal, (expr, _, alias) in enumerate(select, start=1):
                pos_expr = PositionRef(ordinal, alias, expr)  # ty: ignore[invalid-argument-type]
                if alias:
                    selected_exprs[alias] = pos_expr
                selected_exprs[expr] = pos_expr

        for field in ordering:
            if isinstance(field, ResolvableExpression):
                # field is a BaseExpression (has asc/desc/copy methods)
                field_expr = cast(BaseExpression, field)
                if isinstance(field_expr, Value):
                    # output_field must be resolved for constants.
                    field_expr = Cast(field_expr, field_expr.output_field)
                if not isinstance(field_expr, OrderBy):
                    field_expr = field_expr.asc()
                if not self.query.standard_ordering:
                    field_expr = field_expr.copy()
                    field_expr.reverse_ordering()
                field = field_expr
                select_ref = selected_exprs.get(field.expression)
                if select_ref or (
                    isinstance(field.expression, F)
                    and (select_ref := selected_exprs.get(field.expression.name))
                ):
                    field = field.copy()
                    field.expression = select_ref
                yield field, select_ref is not None
                continue
            if field == "?":  # random
                yield OrderBy(Random()), False
                continue

            col, order = get_order_dir(field, default_order)
            descending = order == "DESC"

            if select_ref := selected_exprs.get(col):
                # Reference to expression in SELECT clause
                yield (
                    OrderBy(
                        select_ref,
                        descending=descending,
                    ),
                    True,
                )
                continue
            if col in self.query.annotations:
                # References to an expression which is masked out of the SELECT
                # clause.
                expr = self.query.annotations[col]
                if isinstance(expr, Value):
                    # output_field must be resolved for constants.
                    expr = Cast(expr, expr.output_field)
                yield OrderBy(expr, descending=descending), False
                continue

            if "." in field:
                # This came in through an extra(order_by=...) addition. Pass it
                # on verbatim.
                table, col = col.split(".", 1)
                yield (
                    OrderBy(
                        RawSQL(f"{self.quote_name_unless_alias(table)}.{col}", []),
                        descending=descending,
                    ),
                    False,
                )
                continue

            if self.query.extra and col in self.query.extra:
                if col in self.query.extra_select:
                    yield (
                        OrderBy(
                            Ref(col, RawSQL(*self.query.extra[col])),
                            descending=descending,
                        ),
                        True,
                    )
                else:
                    yield (
                        OrderBy(RawSQL(*self.query.extra[col]), descending=descending),
                        False,
                    )
            else:
                # 'col' is of the form 'field' or 'field1__field2' or
                # '-field1__field2__field', etc.
                assert self.query.model is not None, (
                    "Ordering by fields requires a model"
                )
                meta = self.query.model._model_meta
                yield from self.find_ordering_name(
                    field,
                    meta,
                    default_order=default_order,
                )

    def get_order_by(self) -> list[tuple[Any, tuple[str, tuple, bool]]]:
        """
        Return a list of 2-tuples of the form (expr, (sql, params, is_ref)) for
        the ORDER BY clause.

        The order_by clause can alter the select clause (for example it can add
        aliases to clauses that do not yet have one, or it can add totally new
        select clauses).
        """
        result = []
        seen = set()
        for expr, is_ref in self._order_by_pairs():
            resolved = expr.resolve_expression(self.query, allow_joins=True, reuse=None)
            sql, params = self.compile(resolved)
            # Don't add the same column twice, but the order direction is
            # not taken into account so we strip it. When this entire method
            # is refactored into expressions, then we can check each part as we
            # generate it.
            without_ordering = self.ordering_parts.search(sql)[1]
            params_hash = make_hashable(params)
            if (without_ordering, params_hash) in seen:
                continue
            seen.add((without_ordering, params_hash))
            result.append((resolved, (sql, params, is_ref)))
        return result

    def get_extra_select(
        self, order_by: list[Any], select: list[Any]
    ) -> list[tuple[Any, SqlWithParams, None]]:
        extra_select = []
        if self.query.distinct and not self.query.distinct_fields:
            select_sql = [t[1] for t in select]
            for expr, (sql, params, is_ref) in order_by:
                without_ordering = self.ordering_parts.search(sql)[1]
                if not is_ref and (without_ordering, params) not in select_sql:
                    extra_select.append((expr, (without_ordering, params), None))
        return extra_select

    def quote_name_unless_alias(self, name: str) -> str:
        """
        A wrapper around quote_name() that doesn't quote aliases for table
        names. This avoids problems with some SQL dialects that treat quoted
        strings specially (e.g. PostgreSQL).
        """
        if name in self.quote_cache:
            return self.quote_cache[name]
        if (
            (name in self.query.alias_map and name not in self.query.table_map)
            or name in self.query.extra_select
            or (
                self.query.external_aliases.get(name)
                and name not in self.query.table_map
            )
        ):
            self.quote_cache[name] = name
            return name
        r = quote_name(name)
        self.quote_cache[name] = r
        return r

    def compile(self, node: SQLCompilable) -> SqlWithParams:
        sql, params = node.as_sql(self, self.connection)
        return sql, tuple(params)

    def get_qualify_sql(self) -> tuple[list[str], list[Any]]:
        where_parts = []
        if self.where:
            where_parts.append(self.where)
        if self.having:
            where_parts.append(self.having)
        inner_query = self.query.clone()
        inner_query.subquery = True
        inner_query.where = inner_query.where.__class__(where_parts)
        # Augment the inner query with any window function references that
        # might have been masked via values() and alias(). If any masked
        # aliases are added they'll be masked again to avoid fetching
        # the data in the `if qual_aliases` branch below.
        select = {
            expr: alias for expr, _, alias in self.get_select(with_col_aliases=True)[0]
        }
        select_aliases = set(select.values())
        qual_aliases = set()
        replacements = {}

        def collect_replacements(expressions: list[Any]) -> None:
            while expressions:
                expr = expressions.pop()
                if expr in replacements:
                    continue
                elif select_alias := select.get(expr):
                    replacements[expr] = select_alias
                elif isinstance(expr, Lookup):
                    expressions.extend(expr.get_source_expressions())
                elif isinstance(expr, Ref):
                    if expr.refs not in select_aliases:
                        expressions.extend(expr.get_source_expressions())
                else:
                    num_qual_alias = len(qual_aliases)
                    select_alias = f"qual{num_qual_alias}"
                    qual_aliases.add(select_alias)
                    inner_query.add_annotation(expr, select_alias)
                    replacements[expr] = select_alias

        qualify = self.qualify
        if qualify is None:
            raise ValueError("QUALIFY clause expected but not provided")
        collect_replacements(list(qualify.leaves()))
        qualify = qualify.replace_expressions(
            {expr: Ref(alias, expr) for expr, alias in replacements.items()}
        )
        self.qualify = qualify
        order_by = []
        for order_by_expr, *_ in self.get_order_by():
            collect_replacements(order_by_expr.get_source_expressions())
            order_by.append(
                order_by_expr.replace_expressions(
                    {expr: Ref(alias, expr) for expr, alias in replacements.items()}
                )
            )
        inner_query_compiler = inner_query.get_compiler(elide_empty=self.elide_empty)
        inner_sql, inner_params = inner_query_compiler.as_sql(
            # The limits must be applied to the outer query to avoid pruning
            # results too eagerly.
            with_limits=False,
            # Force unique aliasing of selected columns to avoid collisions
            # and make rhs predicates referencing easier.
            with_col_aliases=True,
        )
        qualify_sql, qualify_params = self.compile(qualify)
        result = [
            "SELECT * FROM (",
            inner_sql,
            ")",
            quote_name("qualify"),
            "WHERE",
            qualify_sql,
        ]
        if qual_aliases:
            # If some select aliases were unmasked for filtering purposes they
            # must be masked back.
            cols = [quote_name(alias) for alias in select.values() if alias is not None]
            result = [
                "SELECT",
                ", ".join(cols),
                "FROM (",
                *result,
                ")",
                quote_name("qualify_mask"),
            ]
        params = list(inner_params) + list(qualify_params)
        # As the SQL spec is unclear on whether or not derived tables
        # ordering must propagate it has to be explicitly repeated on the
        # outer-most query to ensure it's preserved.
        if order_by:
            ordering_sqls = []
            for ordering in order_by:
                ordering_sql, ordering_params = self.compile(ordering)
                ordering_sqls.append(ordering_sql)
                params.extend(ordering_params)
            result.extend(["ORDER BY", ", ".join(ordering_sqls)])
        return result, params

    def as_sql(
        self, with_limits: bool = True, with_col_aliases: bool = False
    ) -> SqlWithParams:
        """
        Create the SQL for this query. Return the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        refcounts_before = self.query.alias_refcount.copy()
        try:
            result = self.pre_sql_setup(with_col_aliases=with_col_aliases)
            assert result is not None  # SQLCompiler.pre_sql_setup always returns tuple
            extra_select, order_by, group_by = result
            assert self.select is not None  # Set by pre_sql_setup()
            for_update_part = None
            # Is a LIMIT/OFFSET clause needed?
            with_limit_offset = with_limits and self.query.is_sliced
            if self.qualify:
                result, params = self.get_qualify_sql()
                order_by = None
            else:
                distinct_fields, distinct_params = self.get_distinct()
                # This must come after 'select', 'ordering', and 'distinct'
                # (see docstring of get_from_clause() for details).
                from_, f_params = self.get_from_clause()
                try:
                    where, w_params = (
                        self.compile(self.where) if self.where is not None else ("", [])
                    )
                except EmptyResultSet:
                    if self.elide_empty:
                        raise
                    # Use a predicate that's always False.
                    where, w_params = "0 = 1", []
                except FullResultSet:
                    where, w_params = "", []
                try:
                    having, h_params = (
                        self.compile(self.having)
                        if self.having is not None
                        else ("", [])
                    )
                except FullResultSet:
                    having, h_params = "", []
                result = ["SELECT"]
                params = []

                if self.query.distinct:
                    distinct_result, distinct_params = distinct_sql(
                        distinct_fields,
                        distinct_params,
                    )
                    result += distinct_result
                    params += distinct_params

                out_cols = []
                for _, (s_sql, s_params), alias in self.select + extra_select:
                    if alias:
                        s_sql = f"{s_sql} AS {quote_name(alias)}"
                    params.extend(s_params)
                    out_cols.append(s_sql)

                result += [", ".join(out_cols)]
                if from_:
                    result += ["FROM", *from_]
                params.extend(f_params)

                if self.query.select_for_update:
                    if self.connection.get_autocommit():
                        raise TransactionManagementError(
                            "select_for_update cannot be used outside of a transaction."
                        )

                    for_update_part = for_update_sql(
                        nowait=self.query.select_for_update_nowait,
                        skip_locked=self.query.select_for_update_skip_locked,
                        of=tuple(self.get_select_for_update_of_arguments()),
                        no_key=self.query.select_for_no_key_update,
                    )

                if where:
                    result.append(f"WHERE {where}")
                    params.extend(w_params)

                grouping = []
                for g_sql, g_params in group_by:
                    grouping.append(g_sql)
                    params.extend(g_params)
                if grouping:
                    if distinct_fields:
                        raise NotImplementedError(
                            "annotate() + distinct(fields) is not implemented."
                        )
                    order_by = order_by or []
                    result.append("GROUP BY {}".format(", ".join(grouping)))
                    if self._meta_ordering:
                        order_by = None
                if having:
                    result.append(f"HAVING {having}")
                    params.extend(h_params)

            if self.query.explain_info:
                result.insert(
                    0,
                    explain_query_prefix(
                        self.query.explain_info.format,
                        **self.query.explain_info.options,
                    ),
                )

            if order_by:
                ordering = []
                for _, (o_sql, o_params, _) in order_by:
                    ordering.append(o_sql)
                    params.extend(o_params)
                result.append("ORDER BY {}".format(", ".join(ordering)))

            if with_limit_offset:
                result.append(
                    limit_offset_sql(self.query.low_mark, self.query.high_mark)
                )

            if for_update_part:
                result.append(for_update_part)

            if self.query.subquery and extra_select:
                # If the query is used as a subquery, the extra selects would
                # result in more columns than the left-hand side expression is
                # expecting. This can happen when a subquery uses a combination
                # of order_by() and distinct(), forcing the ordering expressions
                # to be selected as well. Wrap the query in another subquery
                # to exclude extraneous selects.
                sub_selects = []
                sub_params = []
                for index, (select, _, alias) in enumerate(self.select, start=1):
                    if alias:
                        sub_selects.append(
                            "{}.{}".format(
                                quote_name("subquery"),
                                quote_name(alias),
                            )
                        )
                    else:
                        select_clone = select.relabeled_clone(
                            {select.alias: "subquery"}
                        )
                        subselect, subparams = select_clone.as_sql(
                            self, self.connection
                        )
                        sub_selects.append(subselect)
                        sub_params.extend(subparams)
                return "SELECT {} FROM ({}) subquery".format(
                    ", ".join(sub_selects),
                    " ".join(result),
                ), tuple(sub_params + params)

            return " ".join(result), tuple(params)
        finally:
            # Finally do cleanup - get rid of the joins we created above.
            self.query.reset_refcounts(refcounts_before)

    def get_default_columns(
        self,
        select_mask: Any,
        start_alias: str | None = None,
        opts: Meta | None = None,
    ) -> list[Any]:
        """
        Return Col expressions for every concrete field on the model. When
        pulling in a related model (e.g. via select_related), the caller
        passes ``opts`` and ``start_alias`` to traverse from that join.
        """
        result = []
        if opts is None:
            if self.query.model is None:
                return result
            opts = self.query.model._model_meta
        start_alias = start_alias or self.query.get_initial_alias()

        for field in opts.concrete_fields:
            if select_mask and field not in select_mask:
                continue
            result.append(field.get_col(start_alias))
        return result

    def get_distinct(self) -> tuple[list[str], list]:
        """
        Return a quoted list of fields to use in DISTINCT ON part of the query.

        This method can alter the tables in the query, and thus it must be
        called before get_from_clause().
        """
        result = []
        params = []
        if not self.query.distinct_fields:
            return result, params

        if self.query.model is None:
            return result, params
        opts = self.query.model._model_meta

        for name in self.query.distinct_fields:
            parts = name.split(LOOKUP_SEP)
            _, targets, alias, joins, path, _, transform_function = self._setup_joins(
                parts, opts, None
            )
            targets, alias, _ = self.query.trim_joins(targets, joins, path)
            for target in targets:
                if name in self.query.annotation_select:
                    result.append(quote_name(name))
                else:
                    r, p = self.compile(transform_function(target, alias))
                    result.append(r)
                    params.append(p)
        return result, params

    def find_ordering_name(
        self,
        name: str,
        meta: Meta,
        alias: str | None = None,
        default_order: str = "ASC",
        already_seen: set | None = None,
    ) -> list[tuple[OrderBy, bool]]:
        """
        Return the table alias (the name might be ambiguous, the alias will
        not be) and column name for ordering by the given 'name' parameter.
        The 'name' is of the form 'field1__field2__...__fieldN'.
        """
        name, order = get_order_dir(name, default_order)
        descending = order == "DESC"
        pieces = name.split(LOOKUP_SEP)
        (
            field,
            targets,
            alias,
            joins,
            path,
            meta,
            transform_function,
        ) = self._setup_joins(pieces, meta, alias)

        # If we get to this point and the field is a relation to another model,
        # append the default ordering for that model unless it is the
        # attribute name of the field that is specified or
        # there are transforms to process.
        if (
            isinstance(field, RelatedField)
            and meta.model.model_options.ordering
            and getattr(field, "attname", None) != pieces[-1]
            and not getattr(transform_function, "has_transforms", False)
        ):
            # Firstly, avoid infinite loops.
            already_seen = already_seen or set()
            join_tuple = tuple(
                getattr(self.query.alias_map[j], "join_cols", None) for j in joins
            )
            if join_tuple in already_seen:
                raise FieldError("Infinite loop caused by ordering.")
            already_seen.add(join_tuple)

            results = []
            for item in meta.model.model_options.ordering:
                if isinstance(item, ResolvableExpression) and not isinstance(
                    item, OrderBy
                ):
                    item_expr: BaseExpression = cast(BaseExpression, item)
                    item = item_expr.desc() if descending else item_expr.asc()
                if isinstance(item, OrderBy):
                    results.append(
                        (item.prefix_references(f"{name}{LOOKUP_SEP}"), False)
                    )
                    continue
                results.extend(
                    (expr.prefix_references(f"{name}{LOOKUP_SEP}"), is_ref)
                    for expr, is_ref in self.find_ordering_name(
                        item, meta, alias, order, already_seen
                    )
                )
            return results
        targets, alias, _ = self.query.trim_joins(targets, joins, path)
        return [
            (OrderBy(transform_function(t, alias), descending=descending), False)
            for t in targets
        ]

    def _setup_joins(
        self, pieces: list[str], meta: Meta, alias: str | None
    ) -> tuple[Any, Any, str, list, Any, Meta, Any]:
        """
        Helper method for get_order_by() and get_distinct().

        get_ordering() and get_distinct() must produce same target columns on
        same input, as the prefixes of get_ordering() and get_distinct() must
        match. Executing SQL where this is not true is an error.
        """
        alias = alias or self.query.get_initial_alias()
        assert alias is not None
        field, targets, meta, joins, path, transform_function = self.query.setup_joins(
            pieces, meta, alias
        )
        alias = joins[-1]
        return field, targets, alias, joins, path, meta, transform_function

    def get_from_clause(self) -> tuple[list[str], list]:
        """
        Return a list of strings that are joined together to go after the
        "FROM" part of the query, as well as a list any extra parameters that
        need to be included. Subclasses, can override this to create a
        from-clause via a "select".

        This should only be called after any SQL construction methods that
        might change the tables that are needed. This means the select columns,
        ordering, and distinct must be done first.
        """
        result = []
        params = []
        for alias in tuple(self.query.alias_map):
            if not self.query.alias_refcount[alias]:
                continue
            try:
                from_clause = self.query.alias_map[alias]
            except KeyError:
                # Extra tables can end up in self.tables, but not in the
                # alias_map if they aren't in a join. That's OK. We skip them.
                continue
            clause_sql, clause_params = self.compile(from_clause)
            result.append(clause_sql)
            params.extend(clause_params)
        for t in self.query.extra_tables:
            alias, _ = self.query.table_alias(t)
            # Only add the alias if it's not already present (the table_alias()
            # call increments the refcount, so an alias refcount of one means
            # this is the only reference).
            if (
                alias not in self.query.alias_map
                or self.query.alias_refcount[alias] == 1
            ):
                result.append(f", {self.quote_name_unless_alias(alias)}")
        return result, params

    def get_related_selections(
        self,
        select: list[Any],
        select_mask: Any,
        opts: Meta | None = None,
        root_alias: str | None = None,
        cur_depth: int = 1,
        requested: dict | None = None,
        restricted: bool | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fill in the information needed for a select_related query. The current
        depth is measured as the number of connections away from the root model
        (for example, cur_depth=1 means we are looking at models with direct
        connections to the root model).

        Args:
            opts: Meta for the model being queried (internal metadata)
        """

        related_klass_infos = []
        if not restricted and cur_depth > self.query.max_depth:
            # We've recursed far enough; bail out.
            return related_klass_infos

        if not opts:
            assert self.query.model is not None, "select_related requires a model"
            opts = self.query.model._model_meta
            root_alias = self.query.get_initial_alias()

        assert root_alias is not None  # Must be provided or set above
        assert opts is not None

        def _get_field_choices() -> chain:
            direct_choices = (
                f.name for f in opts.fields if isinstance(f, RelatedField)
            )
            reverse_choices = (
                f.field.related_query_name()
                for f in opts.related_objects
                if f.field.primary_key
            )
            return chain(
                direct_choices, reverse_choices, self.query._filtered_relations
            )

        # Setup for the case when only particular related fields should be
        # included in the related selection.
        fields_found = set()
        if requested is None:
            restricted = isinstance(self.query.select_related, dict)
            if restricted:
                requested = cast(dict, self.query.select_related)

        def get_related_klass_infos(
            klass_info: dict, related_klass_infos: list
        ) -> None:
            klass_info["related_klass_infos"] = related_klass_infos

        for f in opts.fields:
            fields_found.add(f.name)

            if restricted:
                assert requested is not None
                next = requested.get(f.name, {})
                if not isinstance(f, RelatedField):
                    # If a non-related field is used like a relation,
                    # or if a single non-relational field is given.
                    if next or f.name in requested:
                        raise FieldError(
                            "Non-relational field given in select_related: '{}'. "
                            "Choices are: {}".format(
                                f.name,
                                ", ".join(_get_field_choices()) or "(none)",
                            )
                        )
            else:
                next = None

            if not select_related_descend(f, restricted, requested, select_mask):
                continue
            related_select_mask = select_mask.get(f) or {}
            klass_info: dict[str, Any] = {
                "model": f.remote_field.model,
                "field": f,
                "reverse": False,
                "local_setter": f.set_cached_value,
                "remote_setter": f.remote_field.set_cached_value
                if f.primary_key
                else lambda x, y: None,
            }
            related_klass_infos.append(klass_info)
            select_fields = []
            _, _, _, joins, _, _ = self.query.setup_joins([f.name], opts, root_alias)
            alias = joins[-1]
            columns = self.get_default_columns(
                related_select_mask,
                start_alias=alias,
                opts=f.remote_field.model._model_meta,
            )
            for col in columns:
                select_fields.append(len(select))
                select.append((col, None))
            klass_info["select_fields"] = select_fields
            next_klass_infos = self.get_related_selections(
                select,
                related_select_mask,
                f.remote_field.model._model_meta,
                alias,
                cur_depth + 1,
                next,
                restricted,
            )
            get_related_klass_infos(klass_info, next_klass_infos)

        if restricted:
            from plain.postgres.fields.reverse_related import ManyToManyRel

            related_fields = [
                (o.field, o.related_model)
                for o in opts.related_objects
                if o.field.primary_key and not isinstance(o, ManyToManyRel)
            ]
            for related_field, model in related_fields:
                related_select_mask = select_mask.get(related_field) or {}

                if not select_related_descend(
                    related_field,
                    restricted,
                    requested,
                    related_select_mask,
                    reverse=True,
                ):
                    continue

                related_field_name = related_field.related_query_name()
                fields_found.add(related_field_name)

                join_info = self.query.setup_joins(
                    [related_field_name], opts, root_alias
                )
                alias = join_info.joins[-1]
                klass_info: dict[str, Any] = {
                    "model": model,
                    "field": related_field,
                    "reverse": True,
                    "local_setter": related_field.remote_field.set_cached_value,
                    "remote_setter": related_field.set_cached_value,
                }
                related_klass_infos.append(klass_info)
                select_fields = []
                columns = self.get_default_columns(
                    related_select_mask,
                    start_alias=alias,
                    opts=model._model_meta,
                )
                for col in columns:
                    select_fields.append(len(select))
                    select.append((col, None))
                klass_info["select_fields"] = select_fields
                assert requested is not None
                next = requested.get(related_field.related_query_name(), {})
                next_klass_infos = self.get_related_selections(
                    select,
                    related_select_mask,
                    model._model_meta,
                    alias,
                    cur_depth + 1,
                    next,
                    restricted,
                )
                get_related_klass_infos(klass_info, next_klass_infos)

            def local_setter(final_field: Any, obj: Any, from_obj: Any) -> None:
                # Set a reverse fk object when relation is non-empty.
                if from_obj:
                    final_field.remote_field.set_cached_value(from_obj, obj)

            def local_setter_noop(obj: Any, from_obj: Any) -> None:
                pass

            def remote_setter(name: str, obj: Any, from_obj: Any) -> None:
                setattr(from_obj, name, obj)

            assert requested is not None
            for name in list(requested):
                # Filtered relations work only on the topmost level.
                if cur_depth > 1:
                    break
                if name in self.query._filtered_relations:
                    fields_found.add(name)
                    final_field, _, join_opts, joins, _, _ = self.query.setup_joins(
                        [name], opts, root_alias
                    )
                    model = join_opts.model
                    alias = joins[-1]
                    klass_info: dict[str, Any] = {
                        "model": model,
                        "field": final_field,
                        "reverse": True,
                        "local_setter": (
                            partial(local_setter, final_field)
                            if len(joins) <= 2
                            else local_setter_noop
                        ),
                        "remote_setter": partial(remote_setter, name),
                    }
                    related_klass_infos.append(klass_info)
                    select_fields = []
                    field_select_mask = select_mask.get((name, final_field)) or {}
                    columns = self.get_default_columns(
                        field_select_mask,
                        start_alias=alias,
                        opts=model._model_meta,
                    )
                    for col in columns:
                        select_fields.append(len(select))
                        select.append((col, None))
                    klass_info["select_fields"] = select_fields
                    next_requested = requested.get(name, {})
                    next_klass_infos = self.get_related_selections(
                        select,
                        field_select_mask,
                        opts=model._model_meta,
                        root_alias=alias,
                        cur_depth=cur_depth + 1,
                        requested=next_requested,
                        restricted=restricted,
                    )
                    get_related_klass_infos(klass_info, next_klass_infos)
            fields_not_found = set(requested).difference(fields_found)
            if fields_not_found:
                invalid_fields = (f"'{s}'" for s in fields_not_found)
                raise FieldError(
                    "Invalid field name(s) given in select_related: {}. "
                    "Choices are: {}".format(
                        ", ".join(invalid_fields),
                        ", ".join(_get_field_choices()) or "(none)",
                    )
                )
        return related_klass_infos

    def get_select_for_update_of_arguments(self) -> list[str]:
        """
        Return a quoted list of arguments for the SELECT FOR UPDATE OF part of
        the query.
        """

        def _get_first_selected_col_from_model(klass_info: dict) -> Any | None:
            """
            Find the first selected column whose target field belongs to this
            klass_info's model. Returns None when the model isn't represented
            in the select list — callers use that to skip locking the row.
            """
            assert self.select is not None
            model = klass_info["model"]
            for select_index in klass_info["select_fields"]:
                if self.select[select_index][0].target.model == model:
                    return self.select[select_index][0]
            return None

        def _get_field_choices() -> Generator[str]:
            """Yield all allowed field paths in breadth-first search order."""
            queue = collections.deque([(None, self.klass_info)])
            while queue:
                parent_path, klass_info = queue.popleft()
                if parent_path is None:
                    path = []
                    yield "self"
                else:
                    assert klass_info is not None  # Only first iteration has None
                    field = klass_info["field"]
                    if klass_info["reverse"]:
                        field = field.remote_field
                    path = parent_path + [field.name]
                    yield LOOKUP_SEP.join(path)
                if klass_info is not None:
                    queue.extend(
                        (path, related_klass_info)  # type: ignore[invalid-argument-type]
                        for related_klass_info in klass_info.get(
                            "related_klass_infos", []
                        )
                    )

        if not self.klass_info:
            return []
        result = []
        invalid_names = []
        for name in self.query.select_for_update_of:
            klass_info = self.klass_info
            if name == "self":
                col = _get_first_selected_col_from_model(klass_info)
            else:
                for part in name.split(LOOKUP_SEP):
                    if klass_info is None:
                        break
                    klass_infos = (*klass_info.get("related_klass_infos", []),)
                    for related_klass_info in klass_infos:
                        field = related_klass_info["field"]
                        if related_klass_info["reverse"]:
                            field = field.remote_field
                        if field.name == part:
                            klass_info = related_klass_info
                            break
                    else:
                        klass_info = None
                        break
                if klass_info is None:
                    invalid_names.append(name)
                    continue
                col = _get_first_selected_col_from_model(klass_info)
            if col is not None:
                result.append(self.quote_name_unless_alias(col.alias))
        if invalid_names:
            raise FieldError(
                "Invalid field name(s) given in select_for_update(of=(...)): {}. "
                "Only relational fields followed in the query are allowed. "
                "Choices are: {}.".format(
                    ", ".join(invalid_names),
                    ", ".join(_get_field_choices()),
                )
            )
        return result

    def results_iter(
        self,
        results: Any = None,
        tuple_expected: bool = False,
        chunked_fetch: bool = False,
    ) -> Iterable[Any]:
        """Return an iterator over the results from executing this query."""
        if results is None:
            results = self.execute_sql(MULTI, chunked_fetch=chunked_fetch)
        assert self.select is not None  # Set during query execution
        fields = [s[0] for s in self.select[0 : self.col_count]]
        converters = get_converters(fields, self.connection)
        rows = results
        if converters:
            rows = apply_converters(rows, converters, self.connection)
            if tuple_expected:
                rows = map(tuple, rows)
        return rows

    def has_results(self) -> bool:
        """Check if the query returns any results."""
        return bool(self.execute_sql(SINGLE))

    def execute_sql(
        self,
        result_type: str = MULTI,
        chunked_fetch: bool = False,
    ) -> Any:
        """
        Run the query against the database and return the result(s). The
        return value is a single data item if result_type is SINGLE, or a
        flat iterable of rows if the result_type is MULTI.

        result_type is either MULTI (returns a list from fetchall(), or a
        streaming generator from cursor.stream() when chunked_fetch=True),
        SINGLE (only retrieve a single row), or None. In this last case, the
        cursor is returned if any query is executed, since it's used by
        subclasses such as InsertQuery). It's possible, however, that no query
        is needed, as the filters describe an empty set. In that case, None is
        returned, to avoid any unnecessary database interaction.
        """
        result_type = result_type or NO_RESULTS
        try:
            as_sql_result = self.as_sql()
            # SQLCompiler.as_sql returns SqlWithParams, subclasses may differ
            assert isinstance(as_sql_result, tuple)
            assert isinstance(as_sql_result[0], str)
            sql, params = as_sql_result
            if not sql:
                raise EmptyResultSet
        except EmptyResultSet:
            if result_type == MULTI:
                return iter([])
            else:
                return
        cursor = self.connection.cursor()
        if chunked_fetch:
            # Use psycopg3's cursor.stream() for server-side cursor iteration.
            result = cursor.stream(sql, params)
            if self.has_extra_select:
                col_count = self.col_count
                result = (r[:col_count] for r in result)
            return result

        try:
            cursor.execute(sql, params)
        except Exception:
            cursor.close()
            raise

        if result_type == CURSOR:
            # Give the caller the cursor to process and close.
            return cursor
        if result_type == SINGLE:
            try:
                val = cursor.fetchone()
                if val:
                    return val[0 : self.col_count]
                return val
            finally:
                # done with the cursor
                cursor.close()
        if result_type == NO_RESULTS:
            cursor.close()
            return

        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if self.has_extra_select:
            rows = [r[: self.col_count] for r in rows]
        return rows

    def explain_query(self) -> Generator[str]:
        result = self.execute_sql()
        explain_info = self.query.explain_info
        # PostgreSQL may return tuples with integers and strings depending on
        # the EXPLAIN format. Flatten them out into strings.
        format_ = explain_info.format if explain_info is not None else None
        output_formatter = json.dumps if format_ and format_.lower() == "json" else str
        for row in result:
            if not isinstance(row, str):
                yield " ".join(output_formatter(c) for c in row)
            else:
                yield row


class SQLInsertCompiler(SQLCompiler):
    query: InsertQuery
    returning_fields: list | None = None
    returning_params: tuple = ()

    def field_as_sql(self, field: Any, val: Any) -> tuple[str, list]:
        """
        Take a field and a value intended to be saved on that field, and
        return placeholder SQL and accompanying params. Check for raw values,
        expressions, and fields with get_placeholder() defined in that order.

        When field is None, consider the value raw and use it as the
        placeholder, with no corresponding parameters returned.
        """
        if val is DATABASE_DEFAULT:
            # Emit the literal DEFAULT keyword so Postgres uses the column's
            # persistent DEFAULT (e.g. `gen_random_uuid()`). RETURNING then
            # populates the real value back onto the instance.
            sql, params = "DEFAULT", []
        elif field is None:
            # A field value of None means the value is raw.
            sql, params = val, []
        elif hasattr(val, "as_sql"):
            # This is an expression, let's compile it.
            sql, params_tuple = self.compile(val)
            params = list(params_tuple)
        elif hasattr(field, "get_placeholder"):
            # Some fields (e.g. geo fields) need special munging before
            # they can be inserted.
            sql, params = field.get_placeholder(val, self, self.connection), [val]
        else:
            # Return the common case for the placeholder
            sql, params = "%s", [val]

        return sql, list(params)  # Ensure params is a list

    def prepare_value(self, field: Any, value: Any) -> Any:
        """
        Prepare a value to be used in a query by resolving it if it is an
        expression and otherwise calling the field's get_db_prep_save().
        """
        if value is DATABASE_DEFAULT:
            # Carry the sentinel through untouched — field_as_sql will emit
            # the literal DEFAULT keyword.
            return value
        if isinstance(value, ResolvableExpression):
            value = value.resolve_expression(
                self.query, allow_joins=False, for_save=True
            )
            # Don't allow values containing Col expressions. They refer to
            # existing columns on a row, but in the case of insert the row
            # doesn't exist yet.
            if value.contains_column_references:
                raise ValueError(
                    f'Failed to insert expression "{value}" on {field}. F() expressions '
                    "can only be used to update, not to insert."
                )
            if value.contains_aggregate:
                raise FieldError(
                    "Aggregate functions are not allowed in this query "
                    f"({field.name}={value!r})."
                )
            if value.contains_over_clause:
                raise FieldError(
                    f"Window expressions are not allowed in this query ({field.name}={value!r})."
                )
        return field.get_db_prep_save(value, connection=self.connection)

    def pre_save_val(self, field: Any, obj: Any) -> Any:
        """
        Get the given field's value off the given obj. pre_save() is used for
        things like update_now on DateTimeField. Skip it if this is a raw query.
        """
        if self.query.raw:
            return getattr(obj, field.attname)
        return field.pre_save(obj, add=True)

    def assemble_as_sql(
        self, fields: list[Any], value_rows: list[list[Any]]
    ) -> tuple[Any, list[list[Any]]]:
        """
        Take a sequence of N fields and a sequence of M rows of values, and
        generate placeholder SQL and parameters for each field and value.
        Return a pair containing:
         * a sequence of M rows of N SQL placeholder strings, and
         * a sequence of M rows of corresponding parameter values.

        Each placeholder string may contain any number of '%s' interpolation
        strings, and each parameter row will contain exactly as many params
        as the total number of '%s's in the corresponding placeholder row.
        """
        if not value_rows:
            return [], []

        # list of (sql, [params]) tuples for each object to be saved
        # Shape: [n_objs][n_fields][2]
        rows_of_fields_as_sql = (
            (self.field_as_sql(field, v) for field, v in zip(fields, row))
            for row in value_rows
        )

        # tuple like ([sqls], [[params]s]) for each object to be saved
        # Shape: [n_objs][2][n_fields]
        sql_and_param_pair_rows = (zip(*row) for row in rows_of_fields_as_sql)

        # Extract separate lists for placeholders and params.
        # Each of these has shape [n_objs][n_fields]
        placeholder_rows, param_rows = zip(*sql_and_param_pair_rows)

        # Params for each field are still lists, and need to be flattened.
        param_rows = [[p for ps in row for p in ps] for row in param_rows]

        return placeholder_rows, param_rows

    def as_sql(  # ty: ignore[invalid-method-override]  # Returns list for internal iteration in execute_sql
        self, with_limits: bool = True, with_col_aliases: bool = False
    ) -> list[SqlWithParams]:
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = quote_name
        assert self.query.model is not None, "INSERT requires a model"
        meta = self.query.model._model_meta
        options = self.query.model.model_options
        result = [f"INSERT INTO {qn(options.db_table)}"]
        if self.query.fields:
            fields = self.query.fields
        else:
            fields = [meta.get_forward_field("id")]
        result.append("({})".format(", ".join(qn(f.column) for f in fields)))

        if self.query.fields:
            value_rows = [
                [
                    self.prepare_value(field, self.pre_save_val(field, obj))
                    for field in fields
                ]
                for obj in self.query.objs
            ]
        else:
            # An empty object.
            value_rows = [[PK_DEFAULT_VALUE] for _ in self.query.objs]
            fields = [None]

        placeholder_rows, param_rows = self.assemble_as_sql(fields, value_rows)

        conflict_suffix_sql = on_conflict_suffix_sql(
            fields,  # ty: ignore[invalid-argument-type]
            self.query.on_conflict,
            (f.column for f in self.query.update_fields),
            (f.column for f in self.query.unique_fields),
        )
        if self.returning_fields:
            # Use RETURNING clause to get inserted values
            result.append(
                bulk_insert_sql(fields, placeholder_rows)  # ty: ignore[invalid-argument-type]
            )
            params = param_rows
            if conflict_suffix_sql:
                result.append(conflict_suffix_sql)
            # Skip empty r_sql in case returning_cols returns an empty string.
            returning_cols = return_insert_columns(self.returning_fields)
            if returning_cols:
                r_sql, self.returning_params = returning_cols
                if r_sql:
                    result.append(r_sql)
                    params += [list(self.returning_params)]
            return [(" ".join(result), tuple(chain.from_iterable(params)))]

        # Bulk insert without returning fields
        result.append(bulk_insert_sql(fields, placeholder_rows))  # ty: ignore[invalid-argument-type]
        if conflict_suffix_sql:
            result.append(conflict_suffix_sql)
        return [(" ".join(result), tuple(p for ps in param_rows for p in ps))]

    def execute_sql(  # ty: ignore[invalid-method-override]
        self, returning_fields: list | None = None
    ) -> list:
        assert self.query.model is not None, "INSERT execution requires a model"
        options = self.query.model.model_options
        self.returning_fields = returning_fields
        with self.connection.cursor() as cursor:
            for sql, params in self.as_sql():
                cursor.execute(sql, params)
            if not self.returning_fields:
                return []
            # Use RETURNING clause for both single and bulk inserts
            if len(self.query.objs) > 1:
                rows = cursor.fetchall()
            else:
                rows = [cursor.fetchone()]
        cols = [field.get_col(options.db_table) for field in self.returning_fields]
        converters = get_converters(cols, self.connection)
        if converters:
            rows = list(apply_converters(rows, converters, self.connection))
        return rows


class SQLDeleteCompiler(SQLCompiler):
    @cached_property
    def single_alias(self) -> bool:
        # Ensure base table is in aliases.
        self.query.get_initial_alias()
        return sum(self.query.alias_refcount[t] > 0 for t in self.query.alias_map) == 1

    @classmethod
    def _expr_refs_base_model(cls, expr: Any, base_model: Any) -> bool:
        if isinstance(expr, Query):
            return expr.model == base_model
        if not hasattr(expr, "get_source_expressions"):
            return False
        return any(
            cls._expr_refs_base_model(source_expr, base_model)
            for source_expr in expr.get_source_expressions()
        )

    @cached_property
    def contains_self_reference_subquery(self) -> bool:
        return any(
            self._expr_refs_base_model(expr, self.query.model)
            for expr in chain(
                self.query.annotations.values(), self.query.where.children
            )
        )

    def _as_sql(self, query: Query) -> SqlWithParams:
        delete = f"DELETE FROM {self.quote_name_unless_alias(query.base_table)}"  # ty: ignore[invalid-argument-type]
        try:
            where, params = self.compile(query.where)
        except FullResultSet:
            return delete, ()
        return f"{delete} WHERE {where}", tuple(params)

    def as_sql(
        self, with_limits: bool = True, with_col_aliases: bool = False
    ) -> SqlWithParams:
        """
        Create the SQL for this query. Return the SQL string and list of
        parameters.
        """
        if self.single_alias and not self.contains_self_reference_subquery:
            return self._as_sql(self.query)
        innerq = self.query.clone()
        innerq.__class__ = Query
        innerq.clear_select_clause()
        assert self.query.model is not None, "DELETE requires a model"
        id_field = self.query.model._model_meta.get_forward_field("id")
        innerq.select = (id_field.get_col(self.query.get_initial_alias()),)
        outerq = Query(self.query.model)
        outerq.add_filter("id__in", innerq)
        return self._as_sql(outerq)


class SQLUpdateCompiler(SQLCompiler):
    def as_sql(
        self, with_limits: bool = True, with_col_aliases: bool = False
    ) -> SqlWithParams:
        """
        Create the SQL for this query. Return the SQL string and list of
        parameters.
        """
        self.pre_sql_setup()
        query_values = getattr(self.query, "values", None)
        if not query_values:
            return "", ()
        qn = self.quote_name_unless_alias
        values, update_params = [], []
        for field, val in query_values:
            if isinstance(val, ResolvableExpression):
                val = val.resolve_expression(
                    self.query, allow_joins=False, for_save=True
                )
                if val.contains_aggregate:
                    raise FieldError(
                        "Aggregate functions are not allowed in this query "
                        f"({field.name}={val!r})."
                    )
                if val.contains_over_clause:
                    raise FieldError(
                        "Window expressions are not allowed in this query "
                        f"({field.name}={val!r})."
                    )
            elif hasattr(val, "prepare_database_save"):
                if isinstance(field, RelatedField):
                    val = val.prepare_database_save(field)
                else:
                    raise TypeError(
                        f"Tried to update field {field} with a model instance, {val!r}. "
                        f"Use a value compatible with {field.__class__.__name__}."
                    )
            val = field.get_db_prep_save(val, connection=self.connection)

            # Getting the placeholder for the field.
            if hasattr(field, "get_placeholder"):
                placeholder = field.get_placeholder(val, self, self.connection)
            else:
                placeholder = "%s"
            name = field.column
            if hasattr(val, "as_sql"):
                sql, params = self.compile(val)
                values.append(f"{qn(name)} = {placeholder % sql}")
                update_params.extend(params)
            elif val is not None:
                values.append(f"{qn(name)} = {placeholder}")
                update_params.append(val)
            else:
                values.append(f"{qn(name)} = NULL")
        table = self.query.base_table
        result = [
            f"UPDATE {qn(table)} SET",  # ty: ignore[invalid-argument-type]
            ", ".join(values),
        ]
        try:
            where, params = self.compile(self.query.where)
        except FullResultSet:
            params = []
        else:
            result.append(f"WHERE {where}")
        return " ".join(result), tuple(update_params + list(params))

    def execute_sql(self, result_type: str) -> int:  # ty: ignore[invalid-method-override]
        """Execute the update and return the number of rows affected."""
        cursor = super().execute_sql(result_type)
        try:
            return cursor.rowcount if cursor else 0
        finally:
            if cursor:
                cursor.close()

    def pre_sql_setup(
        self, with_col_aliases: bool = False
    ) -> tuple[list[Any], list[Any], list[SqlWithParams]] | None:
        """
        If the update depends on other tables (JOINs in the WHERE clause),
        rewrite the query so the current table is filtered by `id IN (subquery)`.
        """
        refcounts_before = self.query.alias_refcount.copy()
        # Ensure base table is in the query
        self.query.get_initial_alias()
        count = self.query.count_active_tables()
        if count == 1:
            return
        query = self.query.chain(klass=Query)
        query.select_related = False
        query.clear_ordering(force=True)
        query.extra = {}
        query.select = ()
        query.add_fields(["id"])
        super().pre_sql_setup()

        # Reset the where clause and drop the tables we no longer need (they
        # live in the sub-select now).
        self.query.clear_where()
        self.query.add_filter("id__in", query)
        self.query.reset_refcounts(refcounts_before)


class SQLAggregateCompiler(SQLCompiler):
    def as_sql(
        self, with_limits: bool = True, with_col_aliases: bool = False
    ) -> SqlWithParams:
        """
        Create the SQL for this query. Return the SQL string and list of
        parameters.
        """
        sql, params = [], []
        for annotation in self.query.annotation_select.values():
            ann_sql, ann_params = self.compile(annotation)
            ann_sql, ann_params = annotation.select_format(self, ann_sql, ann_params)
            sql.append(ann_sql)
            params.extend(ann_params)
        self.col_count = len(self.query.annotation_select)
        sql = ", ".join(sql)
        params = tuple(params)

        inner_query = cast("AggregateQuery", self.query).inner_query
        inner_query_sql, inner_query_params = inner_query.get_compiler(
            elide_empty=self.elide_empty,
        ).as_sql(with_col_aliases=True)
        sql = f"SELECT {sql} FROM ({inner_query_sql}) subquery"
        params += inner_query_params
        return sql, params
