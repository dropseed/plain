from __future__ import annotations

import logging
import operator
from collections.abc import Callable, Generator
from datetime import datetime
from typing import TYPE_CHECKING, Any

from psycopg import sql as psycopg_sql

if TYPE_CHECKING:
    from typing import Self

from plain.models.backends.constants import DATA_TYPE_CHECK_CONSTRAINTS, DATA_TYPES
from plain.models.backends.ddl_references import (
    Columns,
    Expressions,
    ForeignKeyName,
    IndexColumns,
    IndexName,
    Statement,
    Table,
)
from plain.models.backends.sql import DEFERRABLE_SQL, MAX_NAME_LENGTH, quote_name
from plain.models.backends.utils import names_digest, split_identifier, strip_quotes
from plain.models.constraints import Deferrable
from plain.models.fields import DbParameters, Field
from plain.models.fields.related import ForeignKeyField, RelatedField
from plain.models.fields.reverse_related import ForeignObjectRel, ManyToManyRel
from plain.models.indexes import Index
from plain.models.sql import Query
from plain.models.transaction import atomic
from plain.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Iterable

    from plain.models.backends.wrapper import DatabaseWrapper
    from plain.models.base import Model
    from plain.models.constraints import BaseConstraint
    from plain.models.fields import Field
    from plain.models.fields.related import ForeignKeyField, ManyToManyField
    from plain.models.fields.reverse_related import ManyToManyRel

logger = logging.getLogger("plain.models.backends.schema")


def _is_relevant_relation(relation: ForeignObjectRel, altered_field: Field) -> bool:
    """
    When altering the given field, must constraints on its model from the given
    relation be temporarily dropped?
    """
    from plain.models.fields.related import ManyToManyField

    field = relation.field
    if isinstance(field, ManyToManyField):
        # M2M reverse field
        return False
    if altered_field.primary_key:
        # Foreign key constraint on the primary key, which is being altered.
        return True
    # ForeignKeyField always targets 'id'
    return altered_field.name == "id"


def _all_related_fields(model: type[Model]) -> list[ForeignObjectRel]:
    # Related fields must be returned in a deterministic order.
    return sorted(
        model._model_meta._get_fields(
            forward=False,
            reverse=True,
        ),
        key=operator.attrgetter("name"),
    )


def _related_non_m2m_objects(
    old_field: Field, new_field: Field
) -> Generator[tuple[ForeignObjectRel, ForeignObjectRel], None, None]:
    # Filter out m2m objects from reverse relations.
    # Return (old_relation, new_relation) tuples.
    related_fields = zip(
        (
            obj
            for obj in _all_related_fields(old_field.model)
            if _is_relevant_relation(obj, old_field)
        ),
        (
            obj
            for obj in _all_related_fields(new_field.model)
            if _is_relevant_relation(obj, new_field)
        ),
    )
    for old_rel, new_rel in related_fields:
        yield old_rel, new_rel
        yield from _related_non_m2m_objects(
            old_rel.remote_field,
            new_rel.remote_field,
        )


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
    sql_alter_column_type = "ALTER COLUMN %(column)s TYPE %(type)s%(collation)s"
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

    sql_unique_constraint = "UNIQUE (%(columns)s)%(deferrable)s"
    sql_check_constraint = "CHECK (%(check)s)"
    sql_delete_constraint = "ALTER TABLE %(table)s DROP CONSTRAINT %(name)s"
    sql_constraint = "CONSTRAINT %(name)s %(constraint)s"

    sql_create_check = "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s CHECK (%(check)s)"
    sql_delete_check = sql_delete_constraint

    sql_create_unique = (
        "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s "
        "UNIQUE (%(columns)s)%(deferrable)s"
    )
    sql_delete_unique = sql_delete_constraint

    sql_create_fk = (
        "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) "
        "REFERENCES %(to_table)s (%(to_column)s)%(deferrable)s"
    )
    # Setting the constraint to IMMEDIATE to allow changing data in the same transaction.
    sql_create_column_inline_fk = (
        "CONSTRAINT %(name)s REFERENCES %(to_table)s(%(to_column)s)%(deferrable)s"
        "; SET CONSTRAINTS %(namespace)s%(name)s IMMEDIATE"
    )
    # Setting the constraint to IMMEDIATE runs any deferred checks to allow
    # dropping it in the same transaction.
    sql_delete_fk = (
        "SET CONSTRAINTS %(name)s IMMEDIATE; "
        "ALTER TABLE %(table)s DROP CONSTRAINT %(name)s"
    )

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
    sql_rename_index = "ALTER INDEX %(old_name)s RENAME TO %(new_name)s"
    sql_delete_index = "DROP INDEX IF EXISTS %(name)s"
    sql_delete_index_concurrently = "DROP INDEX CONCURRENTLY IF EXISTS %(name)s"

    sql_create_pk = (
        "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s PRIMARY KEY (%(columns)s)"
    )
    sql_delete_pk = sql_delete_constraint

    sql_alter_table_comment = "COMMENT ON TABLE %(table)s IS %(comment)s"
    sql_alter_column_comment = "COMMENT ON COLUMN %(table)s.%(column)s IS %(comment)s"

    # PostgreSQL IDENTITY column support
    sql_add_identity = (
        "ALTER TABLE %(table)s ALTER COLUMN %(column)s ADD "
        "GENERATED BY DEFAULT AS IDENTITY"
    )
    sql_drop_indentity = (
        "ALTER TABLE %(table)s ALTER COLUMN %(column)s DROP IDENTITY IF EXISTS"
    )
    sql_alter_sequence_type = "ALTER SEQUENCE IF EXISTS %(sequence)s AS %(type)s"
    sql_delete_sequence = "DROP SEQUENCE IF EXISTS %(sequence)s CASCADE"

    def __init__(
        self,
        connection: DatabaseWrapper,
        atomic: bool = True,
    ):
        self.connection = connection
        self.atomic_migration = atomic

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
        logger.debug(
            "%s; (params %r)", sql_str, params, extra={"params": params, "sql": sql_str}
        )

        # Track executed SQL for display in migration output
        self.executed_sql.append(sql_str)

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
            # Check constraints can go on the column SQL here.
            db_params = field.db_parameters(connection=self.connection)
            if db_params["check"]:
                definition += " " + self.sql_check_constraint % db_params
            # Autoincrement SQL (e.g. GENERATED BY DEFAULT AS IDENTITY).
            col_type_suffix = field.db_type_suffix(connection=self.connection)
            if col_type_suffix:
                definition += f" {col_type_suffix}"
            if extra_params:
                params.extend(extra_params)
            # PostgreSQL creates FK constraints via deferred ALTER TABLE
            if isinstance(field, ForeignKeyField) and field.db_constraint:
                self.deferred_sql.append(
                    self._create_fk_sql(model, field, "_fk_%(to_table)s_%(to_column)s")
                )
            # Add the SQL to our big list.
            column_sqls.append(f"{quote_name(field.column)} {definition}")
        constraints = [
            constraint.constraint_sql(model, self)
            for constraint in model.model_options.constraints
        ]
        sql = self.sql_create_table % {
            "table": quote_name(model.model_options.db_table),
            "definition": ", ".join(
                str(constraint)
                for constraint in (*column_sqls, *constraints)
                if constraint
            ),
        }
        return sql, params

    # Field <-> database mapping functions

    def _iter_column_sql(
        self,
        column_db_type: str,
        params: list[Any],
        model: type[Model],
        field: Field,
        field_db_params: DbParameters,
        include_default: bool,
    ) -> Generator[str, None, None]:
        yield column_db_type
        if collation := field_db_params.get("collation"):
            yield "COLLATE " + quote_name(collation)
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
        field_db_params = field.db_parameters(connection=self.connection)
        column_db_type = field_db_params["type"]
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
                    field_db_params,
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
            if field.get_internal_type() == "BinaryField":
                default = b""
            else:
                default = ""
        elif getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            internal_type = field.get_internal_type()
            if internal_type == "DateTimeField":
                default = timezone.now()
            else:
                default = datetime.now()
                if internal_type == "DateField":
                    default = default.date()
                elif internal_type == "TimeField":
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

        # Add table comment.
        if model.model_options.db_table_comment:
            self.alter_db_table_comment(
                model, None, model.model_options.db_table_comment
            )
        # Add column comments.
        for field in model._model_meta.local_fields:
            if field.db_comment:
                field_db_params = field.db_parameters(connection=self.connection)
                field_type = field_db_params["type"]
                assert field_type is not None
                self.execute(
                    *self._alter_column_comment_sql(
                        model, field, field_type, field.db_comment
                    )
                )
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

    def add_index(
        self, model: type[Model], index: Index, concurrently: bool = False
    ) -> None:
        """Add an index on a model."""
        self.execute(
            index.create_sql(model, self, concurrently=concurrently), params=None
        )

    def remove_index(
        self, model: type[Model], index: Index, concurrently: bool = False
    ) -> None:
        """Remove an index from a model."""
        self.execute(index.remove_sql(model, self, concurrently=concurrently))

    def rename_index(
        self, model: type[Model], old_index: Index, new_index: Index
    ) -> None:
        self.execute(
            self._rename_index_sql(model, old_index.name, new_index.name),
            params=None,
        )

    def add_constraint(self, model: type[Model], constraint: BaseConstraint) -> None:
        """Add a constraint to a model."""
        sql = constraint.create_sql(model, self)
        if sql:
            # Constraint.create_sql returns interpolated SQL which makes
            # params=None a necessity to avoid escaping attempts on execution.
            self.execute(sql, params=None)

    def remove_constraint(self, model: type[Model], constraint: BaseConstraint) -> None:
        """Remove a constraint from a model."""
        sql = constraint.remove_sql(model, self)
        if sql:
            self.execute(sql)

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

    def alter_db_table_comment(
        self,
        model: type[Model],
        old_db_table_comment: str | None,
        new_db_table_comment: str | None,
    ) -> None:
        self.execute(
            self.sql_alter_table_comment
            % {
                "table": quote_name(model.model_options.db_table),
                "comment": self.quote_value(new_db_table_comment or ""),
            }
        )

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
        if col_type_suffix := field.db_type_suffix(connection=self.connection):
            definition += f" {col_type_suffix}"
        # Check constraints can go on the column SQL here
        db_params = field.db_parameters(connection=self.connection)
        if db_params["check"]:
            definition += " " + self.sql_check_constraint % db_params
        if isinstance(field, ForeignKeyField) and field.db_constraint:
            # Add FK constraint inline (PostgreSQL always supports this).
            constraint_suffix = "_fk_%(to_table)s_%(to_column)s"
            to_table = field.remote_field.model.model_options.db_table
            field_name = field.remote_field.field_name
            if field_name is None:
                raise ValueError("Foreign key field_name cannot be None")
            to_field = field.remote_field.model._model_meta.get_forward_field(
                field_name
            )
            to_column = to_field.column
            namespace, _ = split_identifier(model.model_options.db_table)
            definition += " " + self.sql_create_column_inline_fk % {
                "name": self._fk_constraint_name(model, field, constraint_suffix),
                "namespace": f"{quote_name(namespace)}." if namespace else "",
                "column": quote_name(field.column),
                "to_table": quote_name(to_table),
                "to_column": quote_name(to_column),
                "deferrable": DEFERRABLE_SQL,
            }
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
        # Add field comment, if required.
        if field.db_comment:
            field_type = db_params["type"]
            assert field_type is not None
            self.execute(
                *self._alter_column_comment_sql(
                    model, field, field_type, field.db_comment
                )
            )
        # Add an index, if required
        self.deferred_sql.extend(self._field_indexes_sql(model, field))

    def remove_field(self, model: type[Model], field: Field) -> None:
        """
        Remove a field from a model. Usually involves deleting a column,
        but for M2Ms may involve deleting a table.
        """
        # It might not actually have a column behind it
        if field.db_parameters(connection=self.connection)["type"] is None:
            return
        # Drop any FK constraints
        if isinstance(field, RelatedField):
            fk_names = self._constraint_names(model, [field.column], foreign_key=True)
            for fk_name in fk_names:
                self.execute(
                    self._delete_constraint_sql(self.sql_delete_fk, model, fk_name)
                )
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
        strict: bool = False,
    ) -> None:
        """
        Allow a field's type, uniqueness, nullability, default, column,
        constraints, etc. to be modified.
        `old_field` is required to compute the necessary changes.
        If `strict` is True, raise errors if the old column does not match
        `old_field` precisely.
        """
        if not self._field_should_be_altered(old_field, new_field):
            return
        # Ensure this field is even column-based
        old_db_params = old_field.db_parameters(connection=self.connection)
        old_type = old_db_params["type"]
        new_db_params = new_field.db_parameters(connection=self.connection)
        new_type = new_db_params["type"]
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
            old_db_params,
            new_db_params,
            strict,
        )

    def _field_db_check(
        self, field: Field, field_db_params: DbParameters
    ) -> str | None:
        # Always check constraints with the same mocked column name to avoid
        # recreating constrains when the column is renamed.
        data = field.db_type_parameters(self.connection)
        data["column"] = "__column_name__"
        try:
            return DATA_TYPE_CHECK_CONSTRAINTS[field.get_internal_type()] % data
        except KeyError:
            return None

    def _field_data_type(
        self, field: Field
    ) -> str | None | Callable[[dict[str, Any]], str]:
        if isinstance(field, RelatedField):
            return field.rel_db_type(self.connection)
        return DATA_TYPES.get(
            field.get_internal_type(),
            field.db_type(self.connection),
        )

    def _get_sequence_name(self, table: str, column: str) -> str | None:
        with self.connection.cursor() as cursor:
            for sequence in self.connection.introspection.get_sequences(cursor, table):
                if sequence["column"] == column:
                    return sequence["name"]
        return None

    def _alter_field(
        self,
        model: type[Model],
        old_field: Field,
        new_field: Field,
        old_type: str,
        new_type: str,
        old_db_params: DbParameters,
        new_db_params: DbParameters,
        strict: bool = False,
    ) -> None:
        """Perform a "physical" (non-ManyToMany) field update."""
        # Drop any FK constraints, we'll remake them later
        fks_dropped = set()
        if (
            isinstance(old_field, ForeignKeyField)
            and old_field.db_constraint
            and self._field_should_be_altered(
                old_field,
                new_field,
                ignore={"db_comment"},
            )
        ):
            fk_names = self._constraint_names(
                model, [old_field.column], foreign_key=True
            )
            if strict and len(fk_names) != 1:
                raise ValueError(
                    f"Found wrong number ({len(fk_names)}) of foreign key constraints for {model.model_options.db_table}.{old_field.column}"
                )
            for fk_name in fk_names:
                fks_dropped.add((old_field.column,))
                self.execute(
                    self._delete_constraint_sql(self.sql_delete_fk, model, fk_name)
                )
        # Has unique been removed?
        if old_field.primary_key and (
            not new_field.primary_key
            or self._field_became_primary_key(old_field, new_field)
        ):
            # Find the unique constraint for this field
            meta_constraint_names = {
                constraint.name for constraint in model.model_options.constraints
            }
            constraint_names = self._constraint_names(
                model,
                [old_field.column],
                unique=True,
                primary_key=False,
                exclude=meta_constraint_names,
            )
            if strict and len(constraint_names) != 1:
                raise ValueError(
                    f"Found wrong number ({len(constraint_names)}) of unique constraints for {model.model_options.db_table}.{old_field.column}"
                )
            for constraint_name in constraint_names:
                sql = self._delete_unique_sql(model, constraint_name)
                if sql is not None:
                    self.execute(sql)
        # Drop incoming FK constraints if the field is a primary key or unique,
        # which might be a to_field target, and things are going to change.
        old_collation = old_db_params.get("collation")
        new_collation = new_db_params.get("collation")
        drop_foreign_keys = (old_field.primary_key and new_field.primary_key) and (
            (old_type != new_type) or (old_collation != new_collation)
        )
        if drop_foreign_keys:
            # '_model_meta.related_field' also contains M2M reverse fields, these
            # will be filtered out
            for _old_rel, new_rel in _related_non_m2m_objects(old_field, new_field):
                rel_fk_names = self._constraint_names(
                    new_rel.related_model, [new_rel.field.column], foreign_key=True
                )
                for fk_name in rel_fk_names:
                    self.execute(
                        self._delete_constraint_sql(
                            self.sql_delete_fk, new_rel.related_model, fk_name
                        )
                    )
        # Removed an index? (no strict check, as multiple indexes are possible)
        # Remove indexes if db_index switched to False or a unique constraint
        # will now be used in lieu of an index. The following lines from the
        # truth table show all True cases; the rest are False:
        #
        # old_field.db_index | old_field.primary_key | new_field.db_index | new_field.primary_key
        # ------------------------------------------------------------------------------
        # True               | False            | False              | False
        # True               | False            | False              | True
        # True               | False            | True               | True
        if (
            isinstance(old_field, ForeignKeyField)
            and old_field.db_index
            and not old_field.primary_key
            and (
                not (isinstance(new_field, ForeignKeyField) and new_field.db_index)
                or new_field.primary_key
            )
        ):
            # Find the index for this field
            meta_index_names = {index.name for index in model.model_options.indexes}
            # Retrieve only BTREE indexes since this is what's created with
            # db_index=True.
            index_names = self._constraint_names(
                model,
                [old_field.column],
                index=True,
                type_=Index.suffix,
                exclude=meta_index_names,
            )
            for index_name in index_names:
                # The only way to check if an index was created with
                # db_index=True or with Index(['field'], name='foo')
                # is to look at its name (refs #28053).
                self.execute(self._delete_index_sql(model, index_name))
        # Change check constraints?
        old_db_check = self._field_db_check(old_field, old_db_params)
        new_db_check = self._field_db_check(new_field, new_db_params)
        if old_db_check != new_db_check and old_db_check:
            meta_constraint_names = {
                constraint.name for constraint in model.model_options.constraints
            }
            constraint_names = self._constraint_names(
                model,
                [old_field.column],
                check=True,
                exclude=meta_constraint_names,
            )
            if strict and len(constraint_names) != 1:
                raise ValueError(
                    f"Found wrong number ({len(constraint_names)}) of check constraints for {model.model_options.db_table}.{old_field.column}"
                )
            for constraint_name in constraint_names:
                sql = self._delete_constraint_sql(
                    self.sql_delete_check, model, constraint_name
                )
                if sql is not None:
                    self.execute(sql)
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
        old_type_suffix = old_field.db_type_suffix(connection=self.connection)
        new_type_suffix = new_field.db_type_suffix(connection=self.connection)
        # Type, collation, or comment change?
        if (
            old_type != new_type
            or old_type_suffix != new_type_suffix
            or old_collation != new_collation
            or old_field.db_comment != new_field.db_comment
        ):
            fragment, other_actions = self._alter_column_type_sql(
                model, old_field, new_field, new_type, old_collation, new_collation
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
        # If primary_key changed to False, delete the primary key constraint.
        if old_field.primary_key and not new_field.primary_key:
            self._delete_primary_key(model, strict)

        # Added an index? Add an index if db_index switched to True or a unique
        # constraint will no longer be used in lieu of an index. The following
        # lines from the truth table show all True cases; the rest are False:
        #
        # old_field.db_index | old_field.primary_key | new_field.db_index | new_field.primary_key
        # ------------------------------------------------------------------------------
        # False              | False            | True               | False
        # False              | True             | True               | False
        # True               | True             | True               | False
        if (
            (
                not (isinstance(old_field, ForeignKeyField) and old_field.db_index)
                or old_field.primary_key
            )
            and isinstance(new_field, ForeignKeyField)
            and new_field.db_index
            and not new_field.primary_key
        ):
            self.execute(self._create_index_sql(model, fields=[new_field]))
        # Type alteration on primary key? Then we need to alter the column
        # referring to us.
        rels_to_update = []
        if drop_foreign_keys:
            rels_to_update.extend(_related_non_m2m_objects(old_field, new_field))
        # Changed to become primary key?
        if self._field_became_primary_key(old_field, new_field):
            # Make the new one
            self.execute(self._create_primary_key_sql(model, new_field))
            # Update all referencing columns
            rels_to_update.extend(_related_non_m2m_objects(old_field, new_field))
        # Handle our type alters on the other end of rels from the PK stuff above
        for old_rel, new_rel in rels_to_update:
            rel_db_params = new_rel.field.db_parameters(connection=self.connection)
            rel_type = rel_db_params["type"]
            rel_collation = rel_db_params.get("collation")
            old_rel_db_params = old_rel.field.db_parameters(connection=self.connection)
            old_rel_collation = old_rel_db_params.get("collation")
            fragment, other_actions = self._alter_column_type_sql(
                new_rel.related_model,
                old_rel.field,
                new_rel.field,
                rel_type,
                old_rel_collation,
                rel_collation,
            )
            self.execute(
                self.sql_alter_column
                % {
                    "table": quote_name(new_rel.related_model.model_options.db_table),
                    "changes": fragment[0],
                },
                fragment[1],
            )
            for sql, params in other_actions:
                self.execute(sql, params)
        # Does it have a foreign key?
        if (
            isinstance(new_field, ForeignKeyField)
            and (
                fks_dropped
                or not isinstance(old_field, ForeignKeyField)
                or not old_field.db_constraint
            )
            and new_field.db_constraint
        ):
            self.execute(
                self._create_fk_sql(model, new_field, "_fk_%(to_table)s_%(to_column)s")
            )
        # Rebuild FKs that pointed to us if we previously had to drop them
        if drop_foreign_keys:
            for _, rel in rels_to_update:
                if isinstance(rel.field, ForeignKeyField) and rel.field.db_constraint:
                    self.execute(
                        self._create_fk_sql(rel.related_model, rel.field, "_fk")
                    )
        # Does it have check constraints we need to add?
        if old_db_check != new_db_check and new_db_check:
            constraint_name = self._create_index_name(
                model.model_options.db_table, [new_field.column], suffix="_check"
            )
            new_check = new_db_params["check"]
            assert new_check is not None  # Guaranteed by new_db_check check above
            sql = self._create_check_sql(model, constraint_name, new_check)
            if sql is not None:
                self.execute(sql)
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

        # Added an index? Create any PostgreSQL-specific indexes.
        if (
            not (
                (isinstance(old_field, ForeignKeyField) and old_field.db_index)
                or old_field.primary_key
            )
            and isinstance(new_field, ForeignKeyField)
            and new_field.db_index
        ) or (not old_field.primary_key and new_field.primary_key):
            like_index_statement = self._create_like_index_sql(model, new_field)
            if like_index_statement is not None:
                self.execute(like_index_statement)

        # Removed an index? Drop any PostgreSQL-specific indexes.
        if old_field.primary_key and not (
            (isinstance(new_field, ForeignKeyField) and new_field.db_index)
            or new_field.primary_key
        ):
            index_to_remove = self._create_index_name(
                model.model_options.db_table, [old_field.column], suffix="_like"
            )
            self.execute(self._delete_index_sql(model, index_to_remove))

    def _alter_column_null_sql(
        self, model: type[Model], old_field: Field, new_field: Field
    ) -> tuple[str, list[Any]]:
        """
        Return a (sql, params) fragment to set a column to null or non-null
        as required by new_field.
        """
        new_db_params = new_field.db_parameters(connection=self.connection)
        sql = (
            self.sql_alter_column_null
            if new_field.allow_null
            else self.sql_alter_column_not_null
        )
        return (
            sql
            % {
                "column": quote_name(new_field.column),
                "type": new_db_params["type"],
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

        new_db_params = new_field.db_parameters(connection=self.connection)
        if drop:
            # PostgreSQL uses the same SQL for nullable and non-nullable columns
            sql = self.sql_alter_column_no_default
        else:
            sql = self.sql_alter_column_default
        return (
            sql
            % {
                "column": quote_name(new_field.column),
                "type": new_db_params["type"],
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
        old_collation: str | None,
        new_collation: str | None,
    ) -> tuple[tuple[str, list[Any]], list[tuple[str, list[Any]]]]:
        """
        Return a two-tuple of: an SQL fragment of (sql, params) to insert into
        an ALTER TABLE statement and a list of extra (sql, params) tuples to
        run once the field is altered. Handles IDENTITY column transitions.
        """
        # Drop indexes on varchar/text/citext columns that are changing to a
        # different type.
        old_db_params = old_field.db_parameters(connection=self.connection)
        old_type = old_db_params["type"]
        assert old_type is not None, "old_type cannot be None for primary key field"
        if old_field.primary_key and (
            (old_type.startswith("varchar") and not new_type.startswith("varchar"))
            or (old_type.startswith("text") and not new_type.startswith("text"))
            or (old_type.startswith("citext") and not new_type.startswith("citext"))
        ):
            index_name = self._create_index_name(
                model.model_options.db_table, [old_field.column], suffix="_like"
            )
            self.execute(self._delete_index_sql(model, index_name))

        self.sql_alter_column_type = (
            "ALTER COLUMN %(column)s TYPE %(type)s%(collation)s"
        )
        # Cast when data type changed.
        if self._field_data_type(old_field) != self._field_data_type(new_field):
            self.sql_alter_column_type += " USING %(column)s::%(type)s"
        new_internal_type = new_field.get_internal_type()
        old_internal_type = old_field.get_internal_type()
        # Make ALTER TYPE with IDENTITY make sense.
        table = strip_quotes(model.model_options.db_table)
        auto_field_types = {"PrimaryKeyField"}
        old_is_auto = old_internal_type in auto_field_types
        new_is_auto = new_internal_type in auto_field_types
        if new_is_auto and not old_is_auto:
            column = strip_quotes(new_field.column)
            return (
                (
                    self.sql_alter_column_type
                    % {
                        "column": quote_name(column),
                        "type": new_type,
                        "collation": "",
                    },
                    [],
                ),
                [
                    (
                        self.sql_add_identity
                        % {
                            "table": quote_name(table),
                            "column": quote_name(column),
                        },
                        [],
                    ),
                ],
            )
        elif old_is_auto and not new_is_auto:
            # Drop IDENTITY if exists (pre-Plain 4.1 serial columns don't have
            # it).
            self.execute(
                self.sql_drop_indentity
                % {
                    "table": quote_name(table),
                    "column": quote_name(strip_quotes(new_field.column)),
                }
            )
            column = strip_quotes(new_field.column)
            fragment, _ = self._alter_column_type_sql_base(
                model, old_field, new_field, new_type, old_collation, new_collation
            )
            # Drop the sequence if exists (Plain 4.1+ identity columns don't
            # have it).
            other_actions: list[tuple[str, list[Any]]] = []
            if sequence_name := self._get_sequence_name(table, column):
                other_actions = [
                    (
                        self.sql_delete_sequence
                        % {
                            "sequence": quote_name(sequence_name),
                        },
                        [],
                    )
                ]
            return fragment, other_actions
        elif new_is_auto and old_is_auto and old_internal_type != new_internal_type:
            fragment, _ = self._alter_column_type_sql_base(
                model, old_field, new_field, new_type, old_collation, new_collation
            )
            column = strip_quotes(new_field.column)
            db_types = {"PrimaryKeyField": "bigint"}
            # Alter the sequence type if exists (Plain 4.1+ identity columns
            # don't have it).
            other_actions: list[tuple[str, list[Any]]] = []
            if sequence_name := self._get_sequence_name(table, column):
                other_actions = [
                    (
                        self.sql_alter_sequence_type
                        % {
                            "sequence": quote_name(sequence_name),
                            "type": db_types[new_internal_type],
                        },
                        [],
                    ),
                ]
            return fragment, other_actions
        else:
            return self._alter_column_type_sql_base(
                model, old_field, new_field, new_type, old_collation, new_collation
            )

    def _alter_column_type_sql_base(
        self,
        model: type[Model],
        old_field: Field,
        new_field: Field,
        new_type: str,
        old_collation: str | None,
        new_collation: str | None,
    ) -> tuple[tuple[str, list[Any]], list[tuple[str, list[Any]]]]:
        """Base implementation of _alter_column_type_sql without IDENTITY handling."""
        other_actions = []
        if new_collation:
            collate_sql = " COLLATE " + quote_name(new_collation)
        else:
            collate_sql = ""
        # Comment change?
        from plain.models.fields.related import ManyToManyField

        comment_sql = ""
        if not isinstance(new_field, ManyToManyField):
            if old_field.db_comment != new_field.db_comment:
                # PostgreSQL can't execute 'ALTER COLUMN ...' and
                # 'COMMENT ON ...' at the same time.
                sql, params = self._alter_column_comment_sql(
                    model, new_field, new_type, new_field.db_comment
                )
                if sql:
                    other_actions.append((sql, params))
            if new_field.db_comment:
                comment_sql = self.quote_value(new_field.db_comment)
        return (
            (
                self.sql_alter_column_type
                % {
                    "column": quote_name(new_field.column),
                    "type": new_type,
                    "collation": collate_sql,
                    "comment": comment_sql,
                },
                [],
            ),
            other_actions,
        )

    def _alter_column_comment_sql(
        self,
        model: type[Model],
        new_field: Field,
        new_type: str,
        new_db_comment: str | None,
    ) -> tuple[str, list[Any]]:
        return (
            self.sql_alter_column_comment
            % {
                "table": quote_name(model.model_options.db_table),
                "column": quote_name(new_field.column),
                "comment": self.quote_value(new_db_comment or ""),
            },
            [],
        )

    def _alter_many_to_many(
        self,
        model: type[Model],
        old_field: ManyToManyField,
        new_field: ManyToManyField,
        strict: bool,
    ) -> None:
        """Alter M2Ms to repoint their to= endpoints."""
        # Type narrow for ManyToManyField.remote_field
        old_rel: ManyToManyRel = old_field.remote_field
        new_rel: ManyToManyRel = new_field.remote_field

        # Rename the through table
        if (
            old_rel.through.model_options.db_table
            != new_rel.through.model_options.db_table
        ):
            self.alter_db_table(
                old_rel.through,
                old_rel.through.model_options.db_table,
                new_rel.through.model_options.db_table,
            )
        # Repoint the FK to the other side
        old_reverse_field = old_rel.through._model_meta.get_forward_field(
            old_field.m2m_reverse_field_name()
        )
        new_reverse_field = new_rel.through._model_meta.get_forward_field(
            new_field.m2m_reverse_field_name()
        )
        self.alter_field(
            new_rel.through,
            # The field that points to the target model is needed, so we can
            # tell alter_field to change it - this is m2m_reverse_field_name()
            # (as opposed to m2m_field_name(), which points to our model).
            old_reverse_field,
            new_reverse_field,
        )
        old_m2m_field = old_rel.through._model_meta.get_forward_field(
            old_field.m2m_field_name()
        )
        new_m2m_field = new_rel.through._model_meta.get_forward_field(
            new_field.m2m_field_name()
        )
        self.alter_field(
            new_rel.through,
            # for self-referential models we need to alter field from the other end too
            old_m2m_field,
            new_m2m_field,
        )

    def _create_index_name(
        self, table_name: str, column_names: list[str], suffix: str = ""
    ) -> str:
        """
        Generate a unique name for an index/unique constraint.

        The name is divided into 3 parts: the table name, the column names,
        and a unique digest and suffix.
        """
        _, table_name = split_identifier(table_name)
        hash_suffix_part = (
            f"{names_digest(table_name, *column_names, length=8)}{suffix}"
        )
        max_length = MAX_NAME_LENGTH
        # If everything fits into max_length, use that name.
        index_name = "{}_{}_{}".format(
            table_name, "_".join(column_names), hash_suffix_part
        )
        if len(index_name) <= max_length:
            return index_name
        # Shorten a long suffix.
        if len(hash_suffix_part) > max_length / 3:
            hash_suffix_part = hash_suffix_part[: max_length // 3]
        other_length = (max_length - len(hash_suffix_part)) // 2 - 1
        index_name = "{}_{}_{}".format(
            table_name[:other_length],
            "_".join(column_names)[:other_length],
            hash_suffix_part,
        )
        # Prepend D if needed to prevent the name from starting with an
        # underscore or a number.
        if index_name[0] == "_" or index_name[0].isdigit():
            index_name = f"D{index_name[:-1]}"
        return index_name

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

    def _rename_index_sql(
        self, model: type[Model], old_name: str, new_name: str
    ) -> Statement:
        return Statement(
            self.sql_rename_index,
            table=Table(model.model_options.db_table),
            old_name=quote_name(old_name),
            new_name=quote_name(new_name),
        )

    def _index_columns(
        self,
        table: str,
        columns: list[str],
        col_suffixes: tuple[str, ...],
        opclasses: tuple[str, ...],
    ) -> Columns | IndexColumns:
        if opclasses:
            return IndexColumns(
                table,
                columns,
                col_suffixes=col_suffixes,
                opclasses=opclasses,
            )
        return Columns(table, columns, col_suffixes=col_suffixes)

    def _model_indexes_sql(self, model: type[Model]) -> list[Statement | None]:
        """
        Return a list of all index SQL statements (field indexes, Meta.indexes) for the specified model.
        """
        output: list[Statement | None] = []
        for field in model._model_meta.local_fields:
            output.extend(self._field_indexes_sql(model, field))

        for index in model.model_options.indexes:
            if not index.contains_expressions:
                output.append(index.create_sql(model, self))
        return output

    def _field_indexes_sql(self, model: type[Model], field: Field) -> list[Statement]:
        """
        Return a list of all index SQL statements for the specified field.
        """
        output: list[Statement] = []
        if self._field_should_be_indexed(model, field):
            output.append(self._create_index_sql(model, fields=[field]))
        # Add LIKE index for varchar/text primary keys
        like_index_statement = self._create_like_index_sql(model, field)
        if like_index_statement is not None:
            output.append(like_index_statement)
        return output

    def _create_like_index_sql(
        self, model: type[Model], field: Field
    ) -> Statement | None:
        """
        Return the statement to create an index with varchar operator pattern
        when the column type is 'varchar' or 'text', otherwise return None.
        """
        db_type = field.db_type(connection=self.connection)
        if db_type is not None and field.primary_key:
            # Fields with database column types of `varchar` and `text` need
            # a second index that specifies their operator class, which is
            # needed when performing correct LIKE queries outside the
            # C locale. See #12234.
            #
            # The same doesn't apply to array fields such as varchar[size]
            # and text[size], so skip them.
            if "[" in db_type:
                return None
            # Non-deterministic collations on Postgresql don't support indexes
            # for operator classes varchar_pattern_ops/text_pattern_ops.
            if getattr(field, "db_collation", None):
                return None
            if db_type.startswith("varchar"):
                return self._create_index_sql(
                    model,
                    fields=[field],
                    suffix="_like",
                    opclasses=("varchar_pattern_ops",),
                )
            elif db_type.startswith("text"):
                return self._create_index_sql(
                    model,
                    fields=[field],
                    suffix="_like",
                    opclasses=("text_pattern_ops",),
                )
        return None

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
        # - adding only a db_column and the column name is not changed
        for attr in ignore.union(old_field.non_db_attrs):
            old_kwargs.pop(attr, None)
        for attr in ignore.union(new_field.non_db_attrs):
            new_kwargs.pop(attr, None)
        return quote_name(old_field.column) != quote_name(new_field.column) or (
            old_path,
            old_args,
            old_kwargs,
        ) != (new_path, new_args, new_kwargs)

    def _field_should_be_indexed(self, model: type[Model], field: Field) -> bool:
        if isinstance(field, ForeignKeyField):
            return bool(field.remote_field) and field.db_index and not field.primary_key
        return False

    def _field_became_primary_key(self, old_field: Field, new_field: Field) -> bool:
        return not old_field.primary_key and new_field.primary_key

    def _rename_field_sql(
        self, table: str, old_field: Field, new_field: Field, new_type: str
    ) -> str:
        return self.sql_rename_column % {
            "table": quote_name(table),
            "old_column": quote_name(old_field.column),
            "new_column": quote_name(new_field.column),
            "type": new_type,
        }

    def _create_fk_sql(
        self, model: type[Model], field: ForeignKeyField, suffix: str
    ) -> Statement:
        table = Table(model.model_options.db_table)
        name = self._fk_constraint_name(model, field, suffix)
        column = Columns(model.model_options.db_table, [field.column])
        to_table = Table(field.target_field.model.model_options.db_table)
        to_column = Columns(
            field.target_field.model.model_options.db_table,
            [field.target_field.column],
        )
        deferrable = DEFERRABLE_SQL
        return Statement(
            self.sql_create_fk,
            table=table,
            name=name,
            column=column,
            to_table=to_table,
            to_column=to_column,
            deferrable=deferrable,
        )

    def _fk_constraint_name(
        self, model: type[Model], field: ForeignKeyField, suffix: str
    ) -> ForeignKeyName:
        def create_fk_name(*args: Any, **kwargs: Any) -> str:
            return quote_name(self._create_index_name(*args, **kwargs))

        return ForeignKeyName(
            model.model_options.db_table,
            [field.column],
            split_identifier(field.target_field.model.model_options.db_table)[1],
            [field.target_field.column],
            suffix,
            create_fk_name,
        )

    def _deferrable_constraint_sql(self, deferrable: Deferrable | None) -> str:
        if deferrable is None:
            return ""
        if deferrable == Deferrable.DEFERRED:
            return " DEFERRABLE INITIALLY DEFERRED"
        if deferrable == Deferrable.IMMEDIATE:
            return " DEFERRABLE INITIALLY IMMEDIATE"
        return ""

    def _unique_sql(
        self,
        model: type[Model],
        fields: Iterable[Field],
        name: str,
        condition: str | None = None,
        deferrable: Deferrable | None = None,
        include: list[str] | None = None,
        opclasses: tuple[str, ...] | None = None,
        expressions: Any = None,
    ) -> str | None:
        if condition or include or opclasses or expressions:
            # Databases support conditional, covering, and functional unique
            # constraints via a unique index.
            sql = self._create_unique_sql(
                model,
                fields,
                name=name,
                condition=condition,
                include=include,
                opclasses=opclasses,
                expressions=expressions,
            )
            if sql:
                self.deferred_sql.append(sql)
            return None
        constraint = self.sql_unique_constraint % {
            "columns": ", ".join([quote_name(field.column) for field in fields]),
            "deferrable": self._deferrable_constraint_sql(deferrable),
        }
        return self.sql_constraint % {
            "name": quote_name(name),
            "constraint": constraint,
        }

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
    ) -> Statement | None:
        compiler = Query(model, alias_cols=False).get_compiler()
        table = model.model_options.db_table
        columns = [field.column for field in fields]
        constraint_name: IndexName | str
        if name is None:
            constraint_name = self._unique_constraint_name(table, columns, quote=True)
        else:
            constraint_name = quote_name(name)
        if condition or include or opclasses or expressions:
            sql = self.sql_create_unique_index
        else:
            sql = self.sql_create_unique
        if columns:
            columns_obj: Columns | IndexColumns | Expressions = self._index_columns(
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

    def _check_sql(self, name: str, check: str) -> str:
        return self.sql_constraint % {
            "name": quote_name(name),
            "constraint": self.sql_check_constraint % {"check": check},
        }

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
            constraints = self.connection.introspection.get_constraints(
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

    def _delete_primary_key(self, model: type[Model], strict: bool = False) -> None:
        constraint_names = self._constraint_names(model, primary_key=True)
        if strict and len(constraint_names) != 1:
            raise ValueError(
                f"Found wrong number ({len(constraint_names)}) of PK constraints for {model.model_options.db_table}"
            )
        for constraint_name in constraint_names:
            self.execute(self._delete_primary_key_sql(model, constraint_name))

    def _create_primary_key_sql(self, model: type[Model], field: Field) -> Statement:
        return Statement(
            self.sql_create_pk,
            table=Table(model.model_options.db_table),
            name=quote_name(
                self._create_index_name(
                    model.model_options.db_table, [field.column], suffix="_pk"
                )
            ),
            columns=Columns(model.model_options.db_table, [field.column]),
        )

    def _delete_primary_key_sql(self, model: type[Model], name: str) -> Statement:
        return self._delete_constraint_sql(self.sql_delete_pk, model, name)
