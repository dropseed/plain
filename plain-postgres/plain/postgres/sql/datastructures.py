"""
Useful auxiliary data structures for query construction. Not useful outside
the SQL domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.dialect import quote_name
from plain.postgres.selectable import Selectable
from plain.postgres.sql.constants import INNER, LOUTER

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.fields.related import ForeignKeyField
    from plain.postgres.fields.reverse_related import ForeignObjectRel
    from plain.postgres.sql.compiler import SQLCompiler


class MultiJoin(Exception):
    """
    Used by join construction code to indicate the point at which a
    multi-valued join was attempted (if the caller wants to treat that
    exceptionally).
    """

    def __init__(
        self, names_pos: int, path_with_names: list[tuple[str, list[Any]]]
    ) -> None:
        self.level = names_pos
        # The path travelled, this includes the path to the multijoin.
        self.names_with_path = path_with_names


class Empty(Selectable[Any]):
    # Query subclasses Selectable (via BaseExpression), shifting its solid
    # base. Query.clone() reassigns __class__ from an Empty to the Query
    # class, so Empty must share that layout.
    pass


class Join:
    """
    Used by sql.Query and sql.SQLCompiler to generate JOIN clauses into the
    FROM entry. For example, the SQL generated could be
        LEFT OUTER JOIN "sometable" T1
        ON ("othertable"."sometable_id" = "sometable"."id")

    This class is primarily used in Query.alias_map. All entries in alias_map
    must be Join compatible by providing the following attributes and methods:
        - table_name (string)
        - table_alias (possible alias for the table, can be None)
        - join_type (can be None for those entries that aren't joined from
          anything)
        - parent_alias (which table is this join's parent, can be None similarly
          to join_type)
        - as_sql()
        - relabeled_clone()
    """

    def __init__(
        self,
        table_name: str,
        parent_alias: str,
        table_alias: str,
        join_type: str,
        join_field: ForeignKeyField | ForeignObjectRel,
        nullable: bool,
    ) -> None:
        # Join table
        self.table_name = table_name
        self.parent_alias = parent_alias
        # Note: table_alias is not necessarily known at instantiation time.
        self.table_alias = table_alias
        # LOUTER or INNER
        self.join_type = join_type
        # The (lhs_col, rhs_col) pair for the JOIN's ON clause. A relation joins
        # on a single column pair.
        self.join_col = join_field.get_joining_columns()
        # Along which field (or ForeignObjectRel in the reverse join case)
        self.join_field = join_field
        # Is this join nullabled?
        self.nullable = nullable

    def as_sql(
        self, compiler: SQLCompiler, connection: DatabaseConnection
    ) -> tuple[str, list[Any]]:
        """
        Generate the full
           LEFT OUTER JOIN sometable ON sometable.somecol = othertable.othercol, params
        clause for this join.
        """
        join_conditions = []
        params = []
        qn = compiler.quote_name_unless_alias
        qn2 = quote_name

        # Add the single join condition for this relation's column pair.
        lhs_col, rhs_col = self.join_col
        join_conditions.append(
            f"{qn(self.parent_alias)}.{qn2(lhs_col)} = {qn(self.table_alias)}.{qn2(rhs_col)}"
        )

        on_clause_sql = " AND ".join(join_conditions)
        alias_str = (
            "" if self.table_alias == self.table_name else (f" {self.table_alias}")
        )
        sql = f"{self.join_type} {qn(self.table_name)}{alias_str} ON ({on_clause_sql})"
        return sql, params

    def relabeled_clone(self, change_map: dict[str, str]) -> Join:
        new_parent_alias = change_map.get(self.parent_alias, self.parent_alias)
        new_table_alias = change_map.get(self.table_alias, self.table_alias)
        return self.__class__(
            self.table_name,
            new_parent_alias,
            new_table_alias,
            self.join_type,
            self.join_field,
            self.nullable,
        )

    @property
    def identity(self) -> tuple[type[Join], str, str, Any]:
        return (
            self.__class__,
            self.table_name,
            self.parent_alias,
            self.join_field,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Join):
            return NotImplemented
        return self.identity == other.identity

    def __hash__(self) -> int:
        return hash(self.identity)

    def demote(self) -> Join:
        new = self.relabeled_clone({})
        new.join_type = INNER
        return new

    def promote(self) -> Join:
        new = self.relabeled_clone({})
        new.join_type = LOUTER
        return new


class BaseTable:
    """
    The BaseTable class is used for base table references in FROM clause. For
    example, the SQL "foo" in
        SELECT * FROM "foo" WHERE somecond
    could be generated by this class.
    """

    join_type = None
    parent_alias = None

    def __init__(self, table_name: str, alias: str) -> None:
        self.table_name = table_name
        self.table_alias = alias

    def as_sql(
        self, compiler: SQLCompiler, connection: DatabaseConnection
    ) -> tuple[str, list[Any]]:
        alias_str = (
            "" if self.table_alias == self.table_name else (f" {self.table_alias}")
        )
        base_sql = compiler.quote_name_unless_alias(self.table_name)
        return base_sql + alias_str, []

    def relabeled_clone(self, change_map: dict[str, str]) -> BaseTable:
        return self.__class__(
            self.table_name, change_map.get(self.table_alias, self.table_alias)
        )

    @property
    def identity(self) -> tuple[type[BaseTable], str, str]:
        return self.__class__, self.table_name, self.table_alias

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseTable):
            return NotImplemented
        return self.identity == other.identity

    def __hash__(self) -> int:
        return hash(self.identity)
