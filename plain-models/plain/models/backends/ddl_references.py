"""
Helpers to manipulate deferred DDL statements that might need to be adjusted or
discarded within when executing a migration.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.sql.compiler import SQLCompiler


class Reference:
    """Base class that defines the reference interface."""

    def references_table(self, table: str) -> bool:
        """
        Return whether or not this instance references the specified table.
        """
        return False

    def references_column(self, table: str, column: str) -> bool:
        """
        Return whether or not this instance references the specified column.
        """
        return False

    def rename_table_references(self, old_table: str, new_table: str) -> None:
        """
        Rename all references to the old_name to the new_table.
        """
        pass

    def rename_column_references(
        self, table: str, old_column: str, new_column: str
    ) -> None:
        """
        Rename all references to the old_column to the new_column.
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {str(self)!r}>"

    def __str__(self) -> str:
        raise NotImplementedError(
            "Subclasses must define how they should be converted to string."
        )


class Table(Reference):
    """Hold a reference to a table."""

    def __init__(self, table: str, quote_name: Callable[[str], str]) -> None:
        self.table = table
        self.quote_name = quote_name

    def references_table(self, table: str) -> bool:
        return self.table == table

    def rename_table_references(self, old_table: str, new_table: str) -> None:
        if self.table == old_table:
            self.table = new_table

    def __str__(self) -> str:
        return self.quote_name(self.table)


class TableColumns(Table):
    """Base class for references to multiple columns of a table."""

    def __init__(self, table: str, columns: list[str]) -> None:
        self.table = table
        self.columns = columns

    def references_column(self, table: str, column: str) -> bool:
        return self.table == table and column in self.columns

    def rename_column_references(
        self, table: str, old_column: str, new_column: str
    ) -> None:
        if self.table == table:
            for index, column in enumerate(self.columns):
                if column == old_column:
                    self.columns[index] = new_column


class Columns(TableColumns):
    """Hold a reference to one or many columns."""

    def __init__(
        self,
        table: str,
        columns: list[str],
        quote_name: Callable[[str], str],
        col_suffixes: tuple[str, ...] = (),
    ) -> None:
        self.quote_name = quote_name
        self.col_suffixes = col_suffixes
        super().__init__(table, columns)

    def __str__(self) -> str:
        def col_str(column: str, idx: int) -> str:
            col = self.quote_name(column)
            try:
                suffix = self.col_suffixes[idx]
                if suffix:
                    col = f"{col} {suffix}"
            except IndexError:
                pass
            return col

        return ", ".join(
            col_str(column, idx) for idx, column in enumerate(self.columns)
        )


class IndexName(TableColumns):
    """Hold a reference to an index name."""

    def __init__(
        self,
        table: str,
        columns: list[str],
        suffix: str,
        create_index_name: Callable[[str, list[str], str], str],
    ) -> None:
        self.suffix = suffix
        self.create_index_name = create_index_name
        super().__init__(table, columns)

    def __str__(self) -> str:
        return self.create_index_name(self.table, self.columns, self.suffix)


class IndexColumns(Columns):
    def __init__(
        self,
        table: str,
        columns: list[str],
        quote_name: Callable[[str], str],
        col_suffixes: tuple[str, ...] = (),
        opclasses: tuple[str, ...] = (),
    ) -> None:
        self.opclasses = opclasses
        super().__init__(table, columns, quote_name, col_suffixes)

    def __str__(self) -> str:
        def col_str(column: str, idx: int) -> str:
            # Index.__init__() guarantees that self.opclasses is the same
            # length as self.columns.
            col = f"{self.quote_name(column)} {self.opclasses[idx]}"
            try:
                suffix = self.col_suffixes[idx]
                if suffix:
                    col = f"{col} {suffix}"
            except IndexError:
                pass
            return col

        return ", ".join(
            col_str(column, idx) for idx, column in enumerate(self.columns)
        )


class ForeignKeyName(TableColumns):
    """Hold a reference to a foreign key name."""

    def __init__(
        self,
        from_table: str,
        from_columns: list[str],
        to_table: str,
        to_columns: list[str],
        suffix_template: str,
        create_fk_name: Callable[[str, list[str], str], str],
    ) -> None:
        self.to_reference = TableColumns(to_table, to_columns)
        self.suffix_template = suffix_template
        self.create_fk_name = create_fk_name
        super().__init__(
            from_table,
            from_columns,
        )

    def references_table(self, table: str) -> bool:
        return super().references_table(table) or self.to_reference.references_table(
            table
        )

    def references_column(self, table: str, column: str) -> bool:
        return super().references_column(
            table, column
        ) or self.to_reference.references_column(table, column)

    def rename_table_references(self, old_table: str, new_table: str) -> None:
        super().rename_table_references(old_table, new_table)
        self.to_reference.rename_table_references(old_table, new_table)

    def rename_column_references(
        self, table: str, old_column: str, new_column: str
    ) -> None:
        super().rename_column_references(table, old_column, new_column)
        self.to_reference.rename_column_references(table, old_column, new_column)

    def __str__(self) -> str:
        suffix = self.suffix_template % {
            "to_table": self.to_reference.table,
            "to_column": self.to_reference.columns[0],
        }
        return self.create_fk_name(self.table, self.columns, suffix)


class Statement(Reference):
    """
    Statement template and formatting parameters container.

    Allows keeping a reference to a statement without interpolating identifiers
    that might have to be adjusted if they're referencing a table or column
    that is removed
    """

    def __init__(self, template: str, **parts: Any) -> None:
        self.template = template
        self.parts = parts

    def references_table(self, table: str) -> bool:
        return any(
            hasattr(part, "references_table") and part.references_table(table)
            for part in self.parts.values()
        )

    def references_column(self, table: str, column: str) -> bool:
        return any(
            hasattr(part, "references_column") and part.references_column(table, column)
            for part in self.parts.values()
        )

    def rename_table_references(self, old_table: str, new_table: str) -> None:
        for part in self.parts.values():
            if hasattr(part, "rename_table_references"):
                part.rename_table_references(old_table, new_table)

    def rename_column_references(
        self, table: str, old_column: str, new_column: str
    ) -> None:
        for part in self.parts.values():
            if hasattr(part, "rename_column_references"):
                part.rename_column_references(table, old_column, new_column)

    def __str__(self) -> str:
        return self.template % self.parts


class Expressions(TableColumns):
    def __init__(
        self,
        table: str,
        expressions: Any,
        compiler: SQLCompiler,
        quote_value: Callable[[Any], str],
    ) -> None:
        self.compiler = compiler
        self.expressions = expressions
        self.quote_value = quote_value
        columns = [
            col.target.column
            for col in self.compiler.query._gen_cols([self.expressions])
        ]
        super().__init__(table, columns)

    def rename_table_references(self, old_table: str, new_table: str) -> None:
        if self.table != old_table:
            return
        self.expressions = self.expressions.relabeled_clone({old_table: new_table})
        super().rename_table_references(old_table, new_table)

    def rename_column_references(
        self, table: str, old_column: str, new_column: str
    ) -> None:
        if self.table != table:
            return
        expressions = deepcopy(self.expressions)
        self.columns = []
        for col in self.compiler.query._gen_cols([expressions]):
            if col.target.column == old_column:
                col.target.column = new_column
            self.columns.append(col.target.column)
        self.expressions = expressions

    def __str__(self) -> str:
        sql, params = self.compiler.compile(self.expressions)
        params = map(self.quote_value, params)
        return sql % tuple(params)
