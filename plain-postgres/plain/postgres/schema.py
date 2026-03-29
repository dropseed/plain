from __future__ import annotations

from collections.abc import Callable, Generator
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from psycopg import sql as psycopg_sql

if TYPE_CHECKING:
    from typing import Self

    from plain.postgres.sql.compiler import SQLCompiler

from plain.logs import get_framework_logger
from plain.postgres.constraints import Deferrable
from plain.postgres.dialect import quote_name
from plain.postgres.fields import (
    BinaryField,
    DateField,
    DateTimeField,
    Field,
    TimeField,
)
from plain.postgres.fields.related import RelatedField
from plain.postgres.fields.reverse_related import ManyToManyRel
from plain.postgres.sql import Query
from plain.postgres.transaction import atomic
from plain.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Iterable

    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.fields import Field

logger = get_framework_logger()


# ##### DDL Reference classes (for deferred DDL statement manipulation) #####


class Table:
    """Hold a reference to a table."""

    def __init__(self, table: str) -> None:
        self.table = table

    def references_table(self, table: str) -> bool:
        return self.table == table

    def references_column(self, table: str, column: str) -> bool:
        return False

    def rename_table_references(self, old_table: str, new_table: str) -> None:
        if self.table == old_table:
            self.table = new_table

    def rename_column_references(
        self, table: str, old_column: str, new_column: str
    ) -> None:
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {str(self)!r}>"

    def __str__(self) -> str:
        return quote_name(self.table)


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
        col_suffixes: tuple[str, ...] = (),
        opclasses: tuple[str, ...] = (),
    ) -> None:
        self.col_suffixes = col_suffixes
        self.opclasses = opclasses
        super().__init__(table, columns)

    def __str__(self) -> str:
        def col_str(column: str, idx: int) -> str:
            col = quote_name(column)
            # If opclasses are provided, include them
            if self.opclasses:
                col = f"{col} {self.opclasses[idx]}"
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


class Statement:
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

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {str(self)!r}>"

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
            for col in self.compiler.query._gen_cols(iter([self.expressions]))
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
        for col in self.compiler.query._gen_cols(iter([expressions])):
            if col.target.column == old_column:
                col.target.column = new_column
            self.columns.append(col.target.column)
        self.expressions = expressions

    def __str__(self) -> str:
        sql, params = self.compiler.compile(self.expressions)
        params = map(self.quote_value, params)
        return sql % tuple(params)


class DatabaseSchemaEditor:
    """
    Responsible for emitting schema-changing statements to PostgreSQL - model
    creation/removal/alteration, field renaming, index management, and so on.
    """

    sql_create_table = "CREATE TABLE %(table)s (%(definition)s)"
    sql_rename_table = "ALTER TABLE %(old_table)s RENAME TO %(new_table)s"
    sql_delete_table = "DROP TABLE %(table)s CASCADE"

    sql_create_column = "ALTER TABLE %(table)s ADD COLUMN %(column)s %(definition)s"
    sql_alter_column = "ALTER TABLE %(table)s %(changes)s"
    sql_alter_column_type = "ALTER COLUMN %(column)s TYPE %(type)s"
    sql_alter_column_null = "ALTER COLUMN %(column)s DROP NOT NULL"
    sql_alter_column_not_null = "ALTER COLUMN %(column)s SET NOT NULL"
    sql_alter_column_default = "ALTER COLUMN %(column)s SET DEFAULT %(default)s"
    sql_alter_column_no_default = "ALTER COLUMN %(column)s DROP DEFAULT"
    sql_delete_column = "ALTER TABLE %(table)s DROP COLUMN %(column)s CASCADE"
    sql_rename_column = (
        "ALTER TABLE %(table)s RENAME COLUMN %(old_column)s TO %(new_column)s"
    )
    # Setting all constraints to IMMEDIATE to allow changing data in the same transaction.
    sql_update_with_default = (
        "UPDATE %(table)s SET %(column)s = %(default)s WHERE %(column)s IS NULL"
        "; SET CONSTRAINTS ALL IMMEDIATE"
    )

    sql_delete_constraint = "ALTER TABLE %(table)s DROP CONSTRAINT %(name)s"
    sql_create_check = "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s CHECK (%(check)s)"
    sql_delete_check = sql_delete_constraint

    sql_create_unique = (
        "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s "
        "UNIQUE (%(columns)s)%(deferrable)s"
    )
    sql_delete_unique = sql_delete_constraint

    sql_create_index = (
        "CREATE INDEX %(name)s ON %(table)s%(using)s "
        "(%(columns)s)%(include)s%(extra)s%(condition)s"
    )
    sql_create_index_concurrently = (
        "CREATE INDEX CONCURRENTLY %(name)s ON %(table)s%(using)s "
        "(%(columns)s)%(include)s%(extra)s%(condition)s"
    )
    sql_create_unique_index = (
        "CREATE UNIQUE INDEX %(name)s ON %(table)s "
        "(%(columns)s)%(include)s%(condition)s"
    )
    sql_create_unique_index_concurrently = (
        "CREATE UNIQUE INDEX CONCURRENTLY %(name)s ON %(table)s "
        "(%(columns)s)%(include)s%(condition)s"
    )
    sql_delete_index = "DROP INDEX IF EXISTS %(name)s"
    sql_delete_index_concurrently = "DROP INDEX CONCURRENTLY IF EXISTS %(name)s"

    def __init__(
        self,
        connection: DatabaseConnection,
        atomic: bool = True,
        collect_sql: bool = False,
    ):
        self.connection = connection
        self.collect_sql = collect_sql
        self.atomic_migration = atomic and not collect_sql

    # State-managing methods

    def __enter__(self) -> Self:
        self.deferred_sql: list[Any] = []
        self.executed_sql: list[str] = []
        if self.atomic_migration:
            self.atomic = atomic()
            self.atomic.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type is None:
            for sql in self.deferred_sql:
                self.execute(sql)
        if self.atomic_migration:
            self.atomic.__exit__(exc_type, exc_value, traceback)
        self.deferred_sql.clear()

    # Core utility functions

    def execute(
        self, sql: str | Statement, params: tuple[Any, ...] | list[Any] | None = ()
    ) -> None:
        """Execute the given SQL statement, with optional parameters."""
        # Account for non-string statement objects.
        sql_str = str(sql)

        # Merge the query client-side, as PostgreSQL won't do it server-side.
        if params is not None:
            sql_str = self.connection.compose_sql(sql_str, params)
            params = None

        # Log the command we're running, then run it
        logger.debug("Schema SQL executed", extra={"sql": sql_str, "params": params})

        # Track executed SQL for display in migration output
        self.executed_sql.append(sql_str)

        if self.collect_sql:
            return

        with self.connection.cursor() as cursor:
            cursor.execute(sql_str, params)

    def quote_value(self, value: Any) -> str:
        """
        Return a quoted version of the value so it's safe to use in an SQL
        string. This is not safe against injection from user code; it is
        intended only for use in making SQL scripts or preparing default values
        (which are not user-defined, so this is safe).
        """
        if isinstance(value, str):
            value = value.replace("%", "%%")
        return psycopg_sql.quote(value, self.connection.connection)

    def table_sql(self, model: type[Model]) -> tuple[str, list[Any]]:
        """Take a model and return its table definition."""
        # Create column SQL, add FK deferreds if needed.
        column_sqls = []
        params = []
        for field in model._model_meta.local_fields:
            # SQL.
            definition, extra_params = self.column_sql(model, field)
            if definition is None:
                continue
            # Autoincrement SQL (e.g. GENERATED BY DEFAULT AS IDENTITY).
            col_type_suffix = field.db_type_suffix()
            if col_type_suffix:
                definition += f" {col_type_suffix}"
            if extra_params:
                params.extend(extra_params)
            # FK constraints are handled by convergence, not during table creation.
            # Add the SQL to our big list.
            column_sqls.append(f"{quote_name(field.column)} {definition}")
        # Constraints are not created inline — they're managed by convergence.
        sql = self.sql_create_table % {
            "table": quote_name(model.model_options.db_table),
            "definition": ", ".join(col for col in column_sqls if col),
        }
        return sql, params

    # Field <-> database mapping functions

    def _iter_column_sql(
        self,
        column_db_type: str,
        params: list[Any],
        model: type[Model],
        field: Field,
        include_default: bool,
    ) -> Generator[str]:
        yield column_db_type
        # Work out nullability.
        null = field.allow_null
        # Include a default value, if requested.
        if include_default:
            default_value = self.effective_default(field)
            if default_value is not None:
                yield "DEFAULT %s"
                params.append(default_value)

        if not null:
            yield "NOT NULL"
        else:
            yield "NULL"

        if field.primary_key:
            yield "PRIMARY KEY"

    def column_sql(
        self, model: type[Model], field: Field, include_default: bool = False
    ) -> tuple[str | None, list[Any] | None]:
        """
        Return the column definition for a field. The field must already have
        had set_attributes_from_name() called.
        """
        # Get the column's type and use that as the basis of the SQL.
        column_db_type = field.db_type()
        # Check for fields that aren't actually columns (e.g. M2M).
        if column_db_type is None:
            return None, None
        params: list[Any] = []
        return (
            " ".join(
                # This appends to the params being returned.
                self._iter_column_sql(
                    column_db_type,
                    params,
                    model,
                    field,
                    include_default,
                )
            ),
            params,
        )

    @staticmethod
    def _effective_default(field: Field) -> Any:
        # This method allows testing its logic without a connection.
        if field.has_default():
            default = field.get_default()
        elif (
            not field.allow_null and not field.required and field.empty_strings_allowed
        ):
            if isinstance(field, BinaryField):
                default = b""
            else:
                default = ""
        elif getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            if isinstance(field, DateTimeField):
                default = timezone.now()
            else:
                default = datetime.now()
                if isinstance(field, DateField):
                    default = default.date()
                elif isinstance(field, TimeField):
                    default = default.time()
        else:
            default = None
        return default

    def effective_default(self, field: Field) -> Any:
        """Return a field's effective database default value."""
        return field.get_db_prep_save(self._effective_default(field), self.connection)

    # Actions

    def create_model(self, model: type[Model]) -> None:
        """
        Create a table and any accompanying indexes or unique constraints for
        the given `model`.
        """
        sql, params = self.table_sql(model)
        # Prevent using [] as params, in the case a literal '%' is used in the
        # definition.
        self.execute(sql, params or None)

        # Add any field indexes.
        self.deferred_sql.extend(self._model_indexes_sql(model))

    def delete_model(self, model: type[Model]) -> None:
        """Delete a model from the database."""

        # Delete the table
        self.execute(
            self.sql_delete_table
            % {
                "table": quote_name(model.model_options.db_table),
            }
        )
        # Remove all deferred statements referencing the deleted table.
        for sql in list(self.deferred_sql):
            if isinstance(sql, Statement) and sql.references_table(
                model.model_options.db_table
            ):
                self.deferred_sql.remove(sql)

    def alter_db_table(
        self, model: type[Model], old_db_table: str, new_db_table: str
    ) -> None:
        """Rename the table a model points to."""
        if old_db_table == new_db_table:
            return
        self.execute(
            self.sql_rename_table
            % {
                "old_table": quote_name(old_db_table),
                "new_table": quote_name(new_db_table),
            }
        )
        # Rename all references to the old table name.
        for sql in self.deferred_sql:
            if isinstance(sql, Statement):
                sql.rename_table_references(old_db_table, new_db_table)

    def add_field(self, model: type[Model], field: Field) -> None:
        """
        Create a field on a model. Usually involves adding a column, but may
        involve adding a table instead (for M2M fields).
        """
        # Get the column's definition
        definition, params = self.column_sql(model, field, include_default=True)
        # It might not actually have a column behind it
        if definition is None:
            return
        if col_type_suffix := field.db_type_suffix():
            definition += f" {col_type_suffix}"
        # FK constraints are handled by convergence, not inline during add_field.
        # Build the SQL and run it
        sql = self.sql_create_column % {
            "table": quote_name(model.model_options.db_table),
            "column": quote_name(field.column),
            "definition": definition,
        }
        self.execute(sql, params)
        # Drop the default if we need to
        # (Plain usually does not use in-database defaults)
        if self.effective_default(field) is not None:
            changes_sql, params = self._alter_column_default_sql(
                model, None, field, drop=True
            )
            sql = self.sql_alter_column % {
                "table": quote_name(model.model_options.db_table),
                "changes": changes_sql,
            }
            self.execute(sql, params)

    def remove_field(self, model: type[Model], field: Field) -> None:
        """
        Remove a field from a model. Usually involves deleting a column,
        but for M2Ms may involve deleting a table.
        """
        # It might not actually have a column behind it
        if field.db_type() is None:
            return
        # FK constraints are dropped automatically by CASCADE on DROP COLUMN.
        # Delete the column
        sql = self.sql_delete_column % {
            "table": quote_name(model.model_options.db_table),
            "column": quote_name(field.column),
        }
        self.execute(sql)
        # Remove all deferred statements referencing the deleted column.
        for sql in list(self.deferred_sql):
            if isinstance(sql, Statement) and sql.references_column(
                model.model_options.db_table, field.column
            ):
                self.deferred_sql.remove(sql)

    def alter_field(
        self,
        model: type[Model],
        old_field: Field,
        new_field: Field,
    ) -> None:
        """
        Allow a field's type, uniqueness, nullability, default, column,
        constraints, etc. to be modified.
        `old_field` is required to compute the necessary changes.
        """
        if not self._field_should_be_altered(old_field, new_field):
            return
        # Ensure this field is even column-based
        old_type = old_field.db_type()
        new_type = new_field.db_type()
        if (old_type is None and not isinstance(old_field, RelatedField)) or (
            new_type is None and not isinstance(new_field, RelatedField)
        ):
            raise ValueError(
                f"Cannot alter field {old_field} into {new_field} - they do not properly define "
                "db_type (are you using a badly-written custom field?)",
            )
        elif (
            old_type is None
            and new_type is None
            and isinstance(old_field, RelatedField)
            and isinstance(old_field.remote_field, ManyToManyRel)
            and isinstance(new_field, RelatedField)
            and isinstance(new_field.remote_field, ManyToManyRel)
        ):
            # Both sides have through models; this is a no-op.
            return
        elif old_type is None or new_type is None:
            raise ValueError(
                f"Cannot alter field {old_field} into {new_field} - they are not compatible types "
                "(you cannot alter to or from M2M fields, or add or remove "
                "through= on M2M fields)"
            )

        self._alter_field(
            model,
            old_field,
            new_field,
            old_type,
            new_type,
        )

    def _field_data_type(self, field: Field) -> str | None:
        if isinstance(field, RelatedField):
            return field.rel_db_type()
        if field.db_type_sql is not None:
            return field.db_type_sql
        return field.db_type()

    def _alter_field(
        self,
        model: type[Model],
        old_field: Field,
        new_field: Field,
        old_type: str,
        new_type: str,
    ) -> None:
        """Perform a "physical" (non-ManyToMany) field update."""
        # FK constraints are managed by convergence, not the schema editor.
        # Have they renamed the column?
        if old_field.column != new_field.column:
            self.execute(
                self._rename_field_sql(
                    model.model_options.db_table, old_field, new_field, new_type
                )
            )
            # Rename all references to the renamed column.
            for sql in self.deferred_sql:
                if isinstance(sql, Statement):
                    sql.rename_column_references(
                        model.model_options.db_table, old_field.column, new_field.column
                    )
        # Next, start accumulating actions to do
        actions = []
        null_actions = []
        post_actions = []
        # Type suffix change? (e.g. auto increment).
        old_type_suffix = old_field.db_type_suffix()
        new_type_suffix = new_field.db_type_suffix()
        # Type change?
        if old_type != new_type or old_type_suffix != new_type_suffix:
            fragment, other_actions = self._alter_column_type_sql(
                model, old_field, new_field, new_type
            )
            actions.append(fragment)
            post_actions.extend(other_actions)
        # When changing a column NULL constraint to NOT NULL with a given
        # default value, we need to perform 4 steps:
        #  1. Add a default for new incoming writes
        #  2. Update existing NULL rows with new default
        #  3. Replace NULL constraint with NOT NULL
        #  4. Drop the default again.
        # Default change?
        needs_database_default = False
        if old_field.allow_null and not new_field.allow_null:
            old_default = self.effective_default(old_field)
            new_default = self.effective_default(new_field)
            if old_default != new_default and new_default is not None:
                needs_database_default = True
                actions.append(
                    self._alter_column_default_sql(model, old_field, new_field)
                )
        # Nullability change?
        if old_field.allow_null != new_field.allow_null:
            fragment = self._alter_column_null_sql(model, old_field, new_field)
            if fragment:
                null_actions.append(fragment)
        # Only if we have a default and there is a change from NULL to NOT NULL
        four_way_default_alteration = new_field.has_default() and (
            old_field.allow_null and not new_field.allow_null
        )
        if actions or null_actions:
            if not four_way_default_alteration:
                # If we don't have to do a 4-way default alteration we can
                # directly run a (NOT) NULL alteration
                actions += null_actions
            # Combine actions together
            if actions:
                sql, params = tuple(zip(*actions))
                actions = [(", ".join(sql), sum(params, []))]
            # Apply those actions
            for sql, params in actions:
                self.execute(
                    self.sql_alter_column
                    % {
                        "table": quote_name(model.model_options.db_table),
                        "changes": sql,
                    },
                    params,
                )
            if four_way_default_alteration:
                # Update existing rows with default value
                self.execute(
                    self.sql_update_with_default
                    % {
                        "table": quote_name(model.model_options.db_table),
                        "column": quote_name(new_field.column),
                        "default": "%s",
                    },
                    [new_default],
                )
                # Since we didn't run a NOT NULL change before we need to do it
                # now
                for sql, params in null_actions:
                    self.execute(
                        self.sql_alter_column
                        % {
                            "table": quote_name(model.model_options.db_table),
                            "changes": sql,
                        },
                        params,
                    )
        if post_actions:
            for sql, params in post_actions:
                self.execute(sql, params)
        # Drop the default if we need to
        # (Plain usually does not use in-database defaults)
        if needs_database_default:
            changes_sql, params = self._alter_column_default_sql(
                model, old_field, new_field, drop=True
            )
            sql = self.sql_alter_column % {
                "table": quote_name(model.model_options.db_table),
                "changes": changes_sql,
            }
            self.execute(sql, params)

    def _alter_column_null_sql(
        self, model: type[Model], old_field: Field, new_field: Field
    ) -> tuple[str, list[Any]]:
        """
        Return a (sql, params) fragment to set a column to null or non-null
        as required by new_field.
        """
        sql = (
            self.sql_alter_column_null
            if new_field.allow_null
            else self.sql_alter_column_not_null
        )
        return (
            sql
            % {
                "column": quote_name(new_field.column),
                "type": new_field.db_type(),
            },
            [],
        )

    def _alter_column_default_sql(
        self,
        model: type[Model],
        old_field: Field | None,
        new_field: Field,
        drop: bool = False,
    ) -> tuple[str, list[Any]]:
        """
        Return a (sql, params) fragment to add or drop (depending on the drop
        argument) a default to new_field's column.
        """
        new_default = self.effective_default(new_field)
        params: list[Any] = [] if drop else [new_default]

        if drop:
            # PostgreSQL uses the same SQL for nullable and non-nullable columns
            sql = self.sql_alter_column_no_default
        else:
            sql = self.sql_alter_column_default
        return (
            sql
            % {
                "column": quote_name(new_field.column),
                "type": new_field.db_type(),
                "default": "%s",
            },
            params,
        )

    def _alter_column_type_sql(
        self,
        model: type[Model],
        old_field: Field,
        new_field: Field,
        new_type: str,
    ) -> tuple[tuple[str, list[Any]], list[tuple[str, list[Any]]]]:
        """
        Return a two-tuple of: an SQL fragment of (sql, params) to insert into
        an ALTER TABLE statement and a list of extra (sql, params) tuples to
        run once the field is altered.
        """
        self.sql_alter_column_type = "ALTER COLUMN %(column)s TYPE %(type)s"
        # Cast when data type changed.
        if self._field_data_type(old_field) != self._field_data_type(new_field):
            self.sql_alter_column_type += " USING %(column)s::%(type)s"
        return (
            (
                self.sql_alter_column_type
                % {
                    "column": quote_name(new_field.column),
                    "type": new_type,
                },
                [],
            ),
            [],
        )

    def _create_index_name(
        self, table_name: str, column_names: list[str], suffix: str = ""
    ) -> str:
        """Generate a unique name for an index/unique constraint."""
        from plain.postgres.utils import generate_identifier_name

        return generate_identifier_name(table_name, column_names, suffix)

    def _index_include_sql(
        self, model: type[Model], columns: list[str] | None
    ) -> str | Statement:
        if not columns:
            return ""
        return Statement(
            " INCLUDE (%(columns)s)",
            columns=Columns(model.model_options.db_table, columns),
        )

    def _create_index_sql(
        self,
        model: type[Model],
        *,
        fields: list[Field] | None = None,
        name: str | None = None,
        suffix: str = "",
        using: str = "",
        col_suffixes: tuple[str, ...] = (),
        sql: str | None = None,
        opclasses: tuple[str, ...] = (),
        condition: str | None = None,
        concurrently: bool = False,
        include: list[str] | None = None,
        expressions: Any = None,
    ) -> Statement:
        """
        Return the SQL statement to create the index for one or several fields
        or expressions. `sql` can be specified if the syntax differs from the
        standard (GIS indexes, ...).
        """
        fields = fields or []
        expressions = expressions or []
        compiler = Query(model, alias_cols=False).get_compiler()
        columns = [field.column for field in fields]
        if sql is None:
            sql = (
                self.sql_create_index
                if not concurrently
                else self.sql_create_index_concurrently
            )
        table = model.model_options.db_table

        def create_index_name(*args: Any, **kwargs: Any) -> str:
            nonlocal name
            if name is None:
                name = self._create_index_name(*args, **kwargs)
            return quote_name(name)

        return Statement(
            sql,
            table=Table(table),
            name=IndexName(table, columns, suffix, create_index_name),
            using=using,
            columns=(
                self._index_columns(table, columns, col_suffixes, opclasses)
                if columns
                else Expressions(table, expressions, compiler, self.quote_value)
            ),
            extra="",
            condition=(" WHERE " + condition if condition else ""),
            include=self._index_include_sql(model, include),
        )

    def _delete_index_sql(
        self,
        model: type[Model],
        name: str,
        sql: str | None = None,
        concurrently: bool = False,
    ) -> Statement:
        if sql is None:
            sql = (
                self.sql_delete_index_concurrently
                if concurrently
                else self.sql_delete_index
            )
        return Statement(
            sql,
            table=Table(model.model_options.db_table),
            name=quote_name(name),
        )

    def _index_columns(
        self,
        table: str,
        columns: list[str],
        col_suffixes: tuple[str, ...],
        opclasses: tuple[str, ...],
    ) -> Columns:
        return Columns(
            table,
            columns,
            col_suffixes=col_suffixes,
            opclasses=opclasses,
        )

    def _model_indexes_sql(self, model: type[Model]) -> list[Statement | None]:
        """
        Return a list of all index SQL statements (Meta.indexes) for the specified model.
        """
        output: list[Statement | None] = []
        for index in model.model_options.indexes:
            if not index.contains_expressions:
                output.append(index.create_sql(model, self))
        return output

    def _field_should_be_altered(
        self, old_field: Field, new_field: Field, ignore: set[str] | None = None
    ) -> bool:
        ignore = ignore or set()
        _, old_path, old_args, old_kwargs = old_field.deconstruct()
        _, new_path, new_args, new_kwargs = new_field.deconstruct()
        # Don't alter when:
        # - changing only a field name
        # - changing an attribute that doesn't affect the schema
        # - changing an attribute in the provided set of ignored attributes
        for attr in ignore.union(old_field.non_db_attrs):
            old_kwargs.pop(attr, None)
        for attr in ignore.union(new_field.non_db_attrs):
            new_kwargs.pop(attr, None)
        return quote_name(old_field.column) != quote_name(new_field.column) or (
            old_path,
            old_args,
            old_kwargs,
        ) != (new_path, new_args, new_kwargs)

    def _rename_field_sql(
        self, table: str, old_field: Field, new_field: Field, new_type: str
    ) -> str:
        return self.sql_rename_column % {
            "table": quote_name(table),
            "old_column": quote_name(old_field.column),
            "new_column": quote_name(new_field.column),
            "type": new_type,
        }

    def _deferrable_constraint_sql(self, deferrable: Deferrable | None) -> str:
        if deferrable is None:
            return ""
        if deferrable == Deferrable.DEFERRED:
            return " DEFERRABLE INITIALLY DEFERRED"
        if deferrable == Deferrable.IMMEDIATE:
            return " DEFERRABLE INITIALLY IMMEDIATE"
        return ""

    def _create_unique_sql(
        self,
        model: type[Model],
        fields: Iterable[Field],
        name: str | None = None,
        condition: str | None = None,
        deferrable: Deferrable | None = None,
        include: list[str] | None = None,
        opclasses: tuple[str, ...] | None = None,
        expressions: Any = None,
        concurrently: bool = False,
    ) -> Statement | None:
        compiler = Query(model, alias_cols=False).get_compiler()
        table = model.model_options.db_table
        columns = [field.column for field in fields]
        constraint_name: IndexName | str
        if name is None:
            constraint_name = self._unique_constraint_name(table, columns, quote=True)
        else:
            constraint_name = quote_name(name)
        if concurrently:
            sql = self.sql_create_unique_index_concurrently
        elif condition or include or opclasses or expressions:
            sql = self.sql_create_unique_index
        else:
            sql = self.sql_create_unique
        if columns:
            columns_obj: Columns | Expressions = self._index_columns(
                table, columns, col_suffixes=(), opclasses=opclasses or ()
            )
        else:
            columns_obj = Expressions(table, expressions, compiler, self.quote_value)
        return Statement(
            sql,
            table=Table(table),
            name=constraint_name,
            columns=columns_obj,
            condition=(" WHERE " + condition if condition else ""),
            deferrable=self._deferrable_constraint_sql(deferrable),
            include=self._index_include_sql(model, include),
        )

    def _unique_constraint_name(
        self, table: str, columns: list[str], quote: bool = True
    ) -> IndexName | str:
        if quote:

            def create_unique_name(*args: Any, **kwargs: Any) -> str:
                return quote_name(self._create_index_name(*args, **kwargs))

        else:
            create_unique_name = self._create_index_name

        return IndexName(table, columns, "_uniq", create_unique_name)

    def _delete_unique_sql(
        self,
        model: type[Model],
        name: str,
        condition: str | None = None,
        deferrable: Deferrable | None = None,
        include: list[str] | None = None,
        opclasses: tuple[str, ...] | None = None,
        expressions: Any = None,
    ) -> Statement:
        if condition or include or opclasses or expressions:
            sql = self.sql_delete_index
        else:
            sql = self.sql_delete_unique
        return self._delete_constraint_sql(sql, model, name)

    def _create_check_sql(self, model: type[Model], name: str, check: str) -> Statement:
        return Statement(
            self.sql_create_check,
            table=Table(model.model_options.db_table),
            name=quote_name(name),
            check=check,
        )

    def _delete_constraint_sql(
        self, template: str, model: type[Model], name: str
    ) -> Statement:
        return Statement(
            template,
            table=Table(model.model_options.db_table),
            name=quote_name(name),
        )

    def _constraint_names(
        self,
        model: type[Model],
        column_names: list[str] | None = None,
        unique: bool | None = None,
        primary_key: bool | None = None,
        index: bool | None = None,
        foreign_key: bool | None = None,
        check: bool | None = None,
        type_: str | None = None,
        exclude: set[str] | None = None,
    ) -> list[str]:
        """Return all constraint names matching the columns and conditions."""
        with self.connection.cursor() as cursor:
            constraints = self.connection.get_constraints(
                cursor, model.model_options.db_table
            )
        result: list[str] = []
        for name, infodict in constraints.items():
            if column_names is None or column_names == infodict["columns"]:
                if unique is not None and infodict["unique"] != unique:
                    continue
                if primary_key is not None and infodict["primary_key"] != primary_key:
                    continue
                if index is not None and infodict["index"] != index:
                    continue
                if check is not None and infodict["check"] != check:
                    continue
                if foreign_key is not None and not infodict["foreign_key"]:
                    continue
                if type_ is not None and infodict["type"] != type_:
                    continue
                if not exclude or name not in exclude:
                    result.append(name)
        return result
