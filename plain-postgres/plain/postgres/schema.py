from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import Self


from plain.logs import get_framework_logger
from plain.postgres.ddl import compile_database_default_sql
from plain.postgres.dialect import build_timeout_set_clauses, quote_name
from plain.postgres.fields import Field
from plain.postgres.fields.base import ColumnField
from plain.postgres.fields.related import RelatedField
from plain.postgres.fields.reverse_related import ManyToManyRel
from plain.postgres.transaction import atomic
from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.fields import Field

logger = get_framework_logger()


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
    sql_alter_column_no_default = "ALTER COLUMN %(column)s DROP DEFAULT"
    sql_delete_column = "ALTER TABLE %(table)s DROP COLUMN %(column)s CASCADE"
    sql_rename_column = (
        "ALTER TABLE %(table)s RENAME COLUMN %(old_column)s TO %(new_column)s"
    )

    def __init__(
        self,
        connection: DatabaseConnection,
        atomic: bool = True,
        collect_sql: bool = False,
    ):
        self.connection = connection
        self.collect_sql = collect_sql
        self.atomic_migration = atomic and not collect_sql
        # `atomic_migration` goes False under collect_sql=True (we don't open
        # a real transaction for preview), but the collected SQL should still
        # reflect a real atomic run. Track the user's `atomic` intent
        # separately so the SET LOCAL prelude is emitted in the atomic=True
        # preview case, and skipped in the atomic=False case (where SET LOCAL
        # would be a no-op with WARNING outside a transaction block).
        self._atomic_intent = atomic

    # State-managing methods

    def __enter__(self) -> Self:
        self.executed_sql: list[str] = []
        if self.atomic_migration:
            self.atomic = atomic()
            self.atomic.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.atomic_migration:
            self.atomic.__exit__(exc_type, exc_value, traceback)

    # Core utility functions

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | list[Any] | None = (),
        *,
        set_timeouts: bool = True,
    ) -> None:
        """Execute the given SQL statement, with optional parameters.

        When ``set_timeouts`` is True (default), ``SET LOCAL lock_timeout`` and
        ``SET LOCAL statement_timeout`` are prepended to the SQL so DDL fails
        fast if it can't acquire its lock or if a blocking statement runs
        longer than configured. Values come from ``POSTGRES_MIGRATION_*``
        settings. ``RunSQL(no_timeout=True)`` passes ``set_timeouts=False`` as
        an escape hatch for long-running data migrations.
        """
        sql_str = sql

        # Merge the query client-side, as PostgreSQL won't do it server-side.
        if params is not None:
            sql_str = self.connection.compose_sql(sql_str, params)
            params = None

        # SET LOCAL only works inside a transaction block. Skip the prelude
        # when the editor was opened with atomic=False (e.g. a migration that
        # needs to issue CONCURRENTLY via RunSQL) — otherwise Postgres would
        # silently WARN and ignore the timeouts. Users of non-atomic
        # migrations manage timeouts explicitly in their RunSQL if needed.
        if set_timeouts and self._atomic_intent:
            sql_str = (
                build_timeout_set_clauses(
                    lock_timeout=plain_settings.POSTGRES_MIGRATION_LOCK_TIMEOUT,
                    statement_timeout=plain_settings.POSTGRES_MIGRATION_STATEMENT_TIMEOUT,
                )
                + sql_str
            )

        # Log the command we're running, then run it
        logger.debug("Schema SQL executed", extra={"sql": sql_str, "params": params})

        # Track executed SQL for display in migration output
        self.executed_sql.append(sql_str)

        if self.collect_sql:
            return

        with self.connection.cursor() as cursor:
            cursor.execute(sql_str, params)

    def table_sql(self, model: type[Model]) -> tuple[str, list[Any]]:
        """Take a model and return its table definition."""
        column_sqls = []
        params = []
        for field in model._model_meta.local_fields:
            definition, extra_params = self.column_sql(
                model, field, include_default=field.has_persistent_column_default()
            )
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
        field: ColumnField,
        include_default: bool,
    ) -> Generator[str]:
        yield column_db_type
        null = field.allow_null
        # Include a default value, if requested.
        if include_default:
            db_default_expr = field.get_db_default_expression()
            if db_default_expr is not None:
                # Expression defaults are inlined into the DDL — they render
                # as parameter-free SQL and become the column's persistent
                # DEFAULT.
                yield f"DEFAULT {self._compile_expression(db_default_expr)}"
            else:
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
        assert isinstance(field, ColumnField)
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

    def _compile_expression(self, expression: Any) -> str:
        """Compile a DB-default expression (Now, GenRandomUUID) for inlining into DDL."""
        return compile_database_default_sql(expression)

    def effective_default(self, field: Field) -> Any:
        """Return a field's declared literal DEFAULT value, prepared for the
        database. Returns None for fields without a user-declared default —
        expression defaults take the `get_db_default_expression()` path
        instead."""
        from plain.postgres.fields.base import DefaultableField

        if not isinstance(field, DefaultableField) or not field.has_default():
            return None
        return field.get_db_prep_save(field.get_default(), self.connection)

    # Actions

    def create_model(self, model: type[Model]) -> None:
        """Create a table for the given model."""
        sql, params = self.table_sql(model)
        # Prevent using [] as params, in the case a literal '%' is used in the
        # definition.
        self.execute(sql, params or None)

    def delete_model(self, model: type[Model]) -> None:
        """Delete a model from the database."""
        self.execute(
            self.sql_delete_table
            % {
                "table": quote_name(model.model_options.db_table),
            }
        )

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

    def add_field(self, model: type[Model], field: Field) -> None:
        """
        Create a field on a model. Usually involves adding a column, but may
        involve adding a table instead (for M2M fields).
        """
        # Get the column's definition
        definition, params = self.column_sql(
            model,
            field,
            include_default=field.has_persistent_column_default(),
        )
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

        assert isinstance(old_field, ColumnField)
        assert isinstance(new_field, ColumnField)
        self._alter_field(
            model,
            old_field,
            new_field,
            old_type,
            new_type,
        )

    def _alter_field(
        self,
        model: type[Model],
        old_field: ColumnField,
        new_field: ColumnField,
        old_type: str,
        new_type: str,
    ) -> None:
        """Column rename + column type change.

        Also drops the existing expression DEFAULT when the column type is
        changing (Postgres rejects the cast otherwise). Nullability and
        column DEFAULT reconciliation are convergence-managed — see
        ``plain.postgres.convergence``.
        """
        if old_field.column != new_field.column:
            self.execute(
                self._rename_field_sql(
                    model.model_options.db_table, old_field, new_field
                )
            )
        # Postgres rejects ALTER COLUMN TYPE when the existing expression DEFAULT
        # can't cast to the new type. Drop it first; convergence re-applies it.
        if old_field.db_returning and old_type != new_type:
            self.execute(
                self.sql_alter_column
                % {
                    "table": quote_name(model.model_options.db_table),
                    "changes": self.sql_alter_column_no_default
                    % {"column": quote_name(new_field.column)},
                }
            )
        if (
            old_type != new_type
            or old_field.db_type_suffix() != new_field.db_type_suffix()
        ):
            type_sql, type_params = self._alter_column_type_sql(
                old_field, new_field, new_type
            )
            self.execute(
                self.sql_alter_column
                % {
                    "table": quote_name(model.model_options.db_table),
                    "changes": type_sql,
                },
                type_params,
            )

    def _alter_column_type_sql(
        self,
        old_field: Field,
        new_field: Field,
        new_type: str,
    ) -> tuple[str, list[Any]]:
        """Return an ``(sql, params)`` ALTER COLUMN TYPE fragment."""
        sql = "ALTER COLUMN %(column)s TYPE %(type)s"
        # USING cast when the base data type changed (e.g. varchar → int),
        # not just a parameter like max_length.
        if old_field.unqualified_db_type() != new_field.unqualified_db_type():
            sql += " USING %(column)s::%(type)s"
        return (
            sql
            % {
                "column": quote_name(new_field.column),
                "type": new_type,
            },
            [],
        )

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
        for attr in ignore.union(old_field.non_migration_attrs):
            old_kwargs.pop(attr, None)
        for attr in ignore.union(new_field.non_migration_attrs):
            new_kwargs.pop(attr, None)
        return quote_name(old_field.column) != quote_name(new_field.column) or (
            old_path,
            old_args,
            old_kwargs,
        ) != (new_path, new_args, new_kwargs)

    def _rename_field_sql(self, table: str, old_field: Field, new_field: Field) -> str:
        return self.sql_rename_column % {
            "table": quote_name(table),
            "old_column": quote_name(old_field.column),
            "new_column": quote_name(new_field.column),
        }
