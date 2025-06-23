import copy
from decimal import Decimal

from plain.models import register_model
from plain.models.backends.base.schema import BaseDatabaseSchemaEditor
from plain.models.backends.ddl_references import Statement
from plain.models.backends.utils import strip_quotes
from plain.models.constraints import UniqueConstraint
from plain.models.db import NotSupportedError
from plain.models.registry import ModelsRegistry
from plain.models.transaction import atomic


class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    sql_delete_table = "DROP TABLE %(table)s"
    sql_create_fk = None
    sql_create_inline_fk = (
        "REFERENCES %(to_table)s (%(to_column)s) DEFERRABLE INITIALLY DEFERRED"
    )
    sql_create_column_inline_fk = sql_create_inline_fk
    sql_delete_column = "ALTER TABLE %(table)s DROP COLUMN %(column)s"
    sql_create_unique = "CREATE UNIQUE INDEX %(name)s ON %(table)s (%(columns)s)"
    sql_delete_unique = "DROP INDEX %(name)s"

    def __enter__(self):
        # Some SQLite schema alterations need foreign key constraints to be
        # disabled. Enforce it here for the duration of the schema edition.
        if not self.connection.disable_constraint_checking():
            raise NotSupportedError(
                "SQLite schema editor cannot be used while foreign key "
                "constraint checks are enabled. Make sure to disable them "
                "before entering a transaction.atomic() context because "
                "SQLite does not support disabling them in the middle of "
                "a multi-statement transaction."
            )
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.check_constraints()
        super().__exit__(exc_type, exc_value, traceback)
        self.connection.enable_constraint_checking()

    def quote_value(self, value):
        # The backend "mostly works" without this function and there are use
        # cases for compiling Python without the sqlite3 libraries (e.g.
        # security hardening).
        try:
            import sqlite3

            value = sqlite3.adapt(value)
        except ImportError:
            pass
        except sqlite3.ProgrammingError:
            pass
        # Manual emulation of SQLite parameter quoting
        if isinstance(value, bool):
            return str(int(value))
        elif isinstance(value, Decimal | float | int):
            return str(value)
        elif isinstance(value, str):
            return "'{}'".format(value.replace("'", "''"))
        elif value is None:
            return "NULL"
        elif isinstance(value, bytes | bytearray | memoryview):
            # Bytes are only allowed for BLOB fields, encoded as string
            # literals containing hexadecimal data and preceded by a single "X"
            # character.
            return f"X'{value.hex()}'"
        else:
            raise ValueError(
                f"Cannot quote parameter value {value!r} of type {type(value)}"
            )

    def prepare_default(self, value):
        return self.quote_value(value)

    def _is_referenced_by_fk_constraint(
        self, table_name, column_name=None, ignore_self=False
    ):
        """
        Return whether or not the provided table name is referenced by another
        one. If `column_name` is specified, only references pointing to that
        column are considered. If `ignore_self` is True, self-referential
        constraints are ignored.
        """
        with self.connection.cursor() as cursor:
            for other_table in self.connection.introspection.get_table_list(cursor):
                if ignore_self and other_table.name == table_name:
                    continue
                relations = self.connection.introspection.get_relations(
                    cursor, other_table.name
                )
                for constraint_column, constraint_table in relations.values():
                    if constraint_table == table_name and (
                        column_name is None or constraint_column == column_name
                    ):
                        return True
        return False

    def alter_db_table(
        self, model, old_db_table, new_db_table, disable_constraints=True
    ):
        if (
            not self.connection.features.supports_atomic_references_rename
            and disable_constraints
            and self._is_referenced_by_fk_constraint(old_db_table)
        ):
            if self.connection.in_atomic_block:
                raise NotSupportedError(
                    f"Renaming the {old_db_table!r} table while in a transaction is not "
                    "supported on SQLite < 3.26 because it would break referential "
                    "integrity. Try adding `atomic = False` to the Migration class."
                )
            self.connection.enable_constraint_checking()
            super().alter_db_table(model, old_db_table, new_db_table)
            self.connection.disable_constraint_checking()
        else:
            super().alter_db_table(model, old_db_table, new_db_table)

    def alter_field(self, model, old_field, new_field, strict=False):
        if not self._field_should_be_altered(old_field, new_field):
            return
        old_field_name = old_field.name
        table_name = model._meta.db_table
        _, old_column_name = old_field.get_attname_column()
        if (
            new_field.name != old_field_name
            and not self.connection.features.supports_atomic_references_rename
            and self._is_referenced_by_fk_constraint(
                table_name, old_column_name, ignore_self=True
            )
        ):
            if self.connection.in_atomic_block:
                raise NotSupportedError(
                    f"Renaming the {model._meta.db_table!r}.{old_field_name!r} column while in a transaction is not "
                    "supported on SQLite < 3.26 because it would break referential "
                    "integrity. Try adding `atomic = False` to the Migration class."
                )
            with atomic():
                super().alter_field(model, old_field, new_field, strict=strict)
                # Follow SQLite's documented procedure for performing changes
                # that don't affect the on-disk content.
                # https://sqlite.org/lang_altertable.html#otheralter
                with self.connection.cursor() as cursor:
                    schema_version = cursor.execute("PRAGMA schema_version").fetchone()[
                        0
                    ]
                    cursor.execute("PRAGMA writable_schema = 1")
                    references_template = f' REFERENCES "{table_name}" ("%s") '
                    new_column_name = new_field.get_attname_column()[1]
                    search = references_template % old_column_name
                    replacement = references_template % new_column_name
                    cursor.execute(
                        "UPDATE sqlite_master SET sql = replace(sql, %s, %s)",
                        (search, replacement),
                    )
                    cursor.execute("PRAGMA schema_version = %d" % (schema_version + 1))  # noqa: UP031
                    cursor.execute("PRAGMA writable_schema = 0")
                    # The integrity check will raise an exception and rollback
                    # the transaction if the sqlite_master updates corrupt the
                    # database.
                    cursor.execute("PRAGMA integrity_check")
            # Perform a VACUUM to refresh the database representation from
            # the sqlite_master table.
            with self.connection.cursor() as cursor:
                cursor.execute("VACUUM")
        else:
            super().alter_field(model, old_field, new_field, strict=strict)

    def _remake_table(
        self, model, create_field=None, delete_field=None, alter_fields=None
    ):
        """
        Shortcut to transform a model from old_model into new_model

        This follows the correct procedure to perform non-rename or column
        addition operations based on SQLite's documentation

        https://www.sqlite.org/lang_altertable.html#caution

        The essential steps are:
          1. Create a table with the updated definition called "new__app_model"
          2. Copy the data from the existing "app_model" table to the new table
          3. Drop the "app_model" table
          4. Rename the "new__app_model" table to "app_model"
          5. Restore any index of the previous "app_model" table.
        """

        # Self-referential fields must be recreated rather than copied from
        # the old model to ensure their remote_field.field_name doesn't refer
        # to an altered field.
        def is_self_referential(f):
            return f.is_relation and f.remote_field.model is model

        # Work out the new fields dict / mapping
        body = {
            f.name: f.clone() if is_self_referential(f) else f
            for f in model._meta.local_concrete_fields
        }
        # Since mapping might mix column names and default values,
        # its values must be already quoted.
        mapping = {
            f.column: self.quote_name(f.column)
            for f in model._meta.local_concrete_fields
        }
        # If any of the new or altered fields is introducing a new PK,
        # remove the old one
        restore_pk_field = None
        alter_fields = alter_fields or []
        if getattr(create_field, "primary_key", False) or any(
            getattr(new_field, "primary_key", False) for _, new_field in alter_fields
        ):
            for name, field in list(body.items()):
                if field.primary_key and not any(
                    # Do not remove the old primary key when an altered field
                    # that introduces a primary key is the same field.
                    name == new_field.name
                    for _, new_field in alter_fields
                ):
                    field.primary_key = False
                    restore_pk_field = field
                    if field.auto_created:
                        del body[name]
                        del mapping[field.column]
        # Add in any created fields
        if create_field:
            body[create_field.name] = create_field
            # Choose a default and insert it into the copy map
            if not create_field.many_to_many and create_field.concrete:
                mapping[create_field.column] = self.prepare_default(
                    self.effective_default(create_field),
                )
        # Add in any altered fields
        for alter_field in alter_fields:
            old_field, new_field = alter_field
            body.pop(old_field.name, None)
            mapping.pop(old_field.column, None)
            body[new_field.name] = new_field
            if old_field.allow_null and not new_field.allow_null:
                case_sql = f"coalesce({self.quote_name(old_field.column)}, {self.prepare_default(self.effective_default(new_field))})"
                mapping[new_field.column] = case_sql
            else:
                mapping[new_field.column] = self.quote_name(old_field.column)
        # Remove any deleted fields
        if delete_field:
            del body[delete_field.name]
            del mapping[delete_field.column]
        # Work inside a new app registry
        models_registry = ModelsRegistry()

        indexes = model._meta.indexes
        if delete_field:
            indexes = [
                index for index in indexes if delete_field.name not in index.fields
            ]

        constraints = list(model._meta.constraints)

        # Provide isolated instances of the fields to the new model body so
        # that the existing model's internals aren't interfered with when
        # the dummy model is constructed.
        body_copy = copy.deepcopy(body)

        # Construct a new model with the new fields to allow self referential
        # primary key to resolve to. This model won't ever be materialized as a
        # table and solely exists for foreign key reference resolution purposes.
        # This wouldn't be required if the schema editor was operating on model
        # states instead of rendered models.
        meta_contents = {
            "package_label": model._meta.package_label,
            "db_table": model._meta.db_table,
            "indexes": indexes,
            "constraints": constraints,
            "models_registry": models_registry,
        }
        meta = type("Meta", (), meta_contents)
        body_copy["Meta"] = meta
        body_copy["__module__"] = model.__module__
        register_model(type(model._meta.object_name, model.__bases__, body_copy))

        # Construct a model with a renamed table name.
        body_copy = copy.deepcopy(body)
        meta_contents = {
            "package_label": model._meta.package_label,
            "db_table": f"new__{strip_quotes(model._meta.db_table)}",
            "indexes": indexes,
            "constraints": constraints,
            "models_registry": models_registry,
        }
        meta = type("Meta", (), meta_contents)
        body_copy["Meta"] = meta
        body_copy["__module__"] = model.__module__
        new_model = type(f"New{model._meta.object_name}", model.__bases__, body_copy)
        register_model(new_model)

        # Create a new table with the updated schema.
        self.create_model(new_model)

        # Copy data from the old table into the new table
        self.execute(
            "INSERT INTO {} ({}) SELECT {} FROM {}".format(
                self.quote_name(new_model._meta.db_table),
                ", ".join(self.quote_name(x) for x in mapping),
                ", ".join(mapping.values()),
                self.quote_name(model._meta.db_table),
            )
        )

        # Delete the old table to make way for the new
        self.delete_model(model, handle_autom2m=False)

        # Rename the new table to take way for the old
        self.alter_db_table(
            new_model,
            new_model._meta.db_table,
            model._meta.db_table,
            disable_constraints=False,
        )

        # Run deferred SQL on correct table
        for sql in self.deferred_sql:
            self.execute(sql)
        self.deferred_sql = []
        # Fix any PK-removed field
        if restore_pk_field:
            restore_pk_field.primary_key = True

    def delete_model(self, model, handle_autom2m=True):
        if handle_autom2m:
            super().delete_model(model)
        else:
            # Delete the table (and only that)
            self.execute(
                self.sql_delete_table
                % {
                    "table": self.quote_name(model._meta.db_table),
                }
            )
            # Remove all deferred statements referencing the deleted table.
            for sql in list(self.deferred_sql):
                if isinstance(sql, Statement) and sql.references_table(
                    model._meta.db_table
                ):
                    self.deferred_sql.remove(sql)

    def add_field(self, model, field):
        """Create a field on a model."""
        if (
            # Primary keys are not supported in ALTER TABLE
            # ADD COLUMN.
            field.primary_key
            or
            # Fields with default values cannot by handled by ALTER TABLE ADD
            # COLUMN statement because DROP DEFAULT is not supported in
            # ALTER TABLE.
            not field.allow_null
            or self.effective_default(field) is not None
        ):
            self._remake_table(model, create_field=field)
        else:
            super().add_field(model, field)

    def remove_field(self, model, field):
        """
        Remove a field from a model. Usually involves deleting a column,
        but for M2Ms may involve deleting a table.
        """
        # M2M fields are a special case
        if field.many_to_many:
            # For explicit "through" M2M fields, do nothing
            pass
        elif (
            self.connection.features.can_alter_table_drop_column
            # Primary keys, unique fields, indexed fields, and foreign keys are
            # not supported in ALTER TABLE DROP COLUMN.
            and not field.primary_key
            and not (field.remote_field and field.db_index)
            and not (field.remote_field and field.db_constraint)
        ):
            super().remove_field(model, field)
        # For everything else, remake.
        else:
            # It might not actually have a column behind it
            if field.db_parameters(connection=self.connection)["type"] is None:
                return
            self._remake_table(model, delete_field=field)

    def _alter_field(
        self,
        model,
        old_field,
        new_field,
        old_type,
        new_type,
        old_db_params,
        new_db_params,
        strict=False,
    ):
        """Perform a "physical" (non-ManyToMany) field update."""
        # Use "ALTER TABLE ... RENAME COLUMN" if only the column name
        # changed and there aren't any constraints.
        if (
            self.connection.features.can_alter_table_rename_column
            and old_field.column != new_field.column
            and self.column_sql(model, old_field) == self.column_sql(model, new_field)
            and not (
                old_field.remote_field
                and old_field.db_constraint
                or new_field.remote_field
                and new_field.db_constraint
            )
        ):
            return self.execute(
                self._rename_field_sql(
                    model._meta.db_table, old_field, new_field, new_type
                )
            )
        # Alter by remaking table
        self._remake_table(model, alter_fields=[(old_field, new_field)])
        # Rebuild tables with FKs pointing to this field.
        old_collation = old_db_params.get("collation")
        new_collation = new_db_params.get("collation")
        if new_field.primary_key and (
            old_type != new_type or old_collation != new_collation
        ):
            related_models = set()
            opts = new_field.model._meta
            for remote_field in opts.related_objects:
                # Ignore self-relationship since the table was already rebuilt.
                if remote_field.related_model == model:
                    continue
                if not remote_field.many_to_many:
                    if remote_field.field_name == new_field.name:
                        related_models.add(remote_field.related_model)
            if new_field.primary_key:
                for many_to_many in opts.many_to_many:
                    # Ignore self-relationship since the table was already rebuilt.
                    if many_to_many.related_model == model:
                        continue
            for related_model in related_models:
                self._remake_table(related_model)

    def _alter_many_to_many(self, model, old_field, new_field, strict):
        """Alter M2Ms to repoint their to= endpoints."""
        if (
            old_field.remote_field.through._meta.db_table
            == new_field.remote_field.through._meta.db_table
        ):
            # The field name didn't change, but some options did, so we have to
            # propagate this altering.
            self._remake_table(
                old_field.remote_field.through,
                alter_fields=[
                    (
                        # The field that points to the target model is needed,
                        # so that table can be remade with the new m2m field -
                        # this is m2m_reverse_field_name().
                        old_field.remote_field.through._meta.get_field(
                            old_field.m2m_reverse_field_name()
                        ),
                        new_field.remote_field.through._meta.get_field(
                            new_field.m2m_reverse_field_name()
                        ),
                    ),
                    (
                        # The field that points to the model itself is needed,
                        # so that table can be remade with the new self field -
                        # this is m2m_field_name().
                        old_field.remote_field.through._meta.get_field(
                            old_field.m2m_field_name()
                        ),
                        new_field.remote_field.through._meta.get_field(
                            new_field.m2m_field_name()
                        ),
                    ),
                ],
            )
            return

        # Make a new through table
        self.create_model(new_field.remote_field.through)
        # Copy the data across
        self.execute(
            "INSERT INTO {} ({}) SELECT {} FROM {}".format(
                self.quote_name(new_field.remote_field.through._meta.db_table),
                ", ".join(
                    [
                        "id",
                        new_field.m2m_column_name(),
                        new_field.m2m_reverse_name(),
                    ]
                ),
                ", ".join(
                    [
                        "id",
                        old_field.m2m_column_name(),
                        old_field.m2m_reverse_name(),
                    ]
                ),
                self.quote_name(old_field.remote_field.through._meta.db_table),
            )
        )
        # Delete the old through table
        self.delete_model(old_field.remote_field.through)

    def add_constraint(self, model, constraint):
        if isinstance(constraint, UniqueConstraint) and (
            constraint.condition
            or constraint.contains_expressions
            or constraint.include
            or constraint.deferrable
        ):
            super().add_constraint(model, constraint)
        else:
            self._remake_table(model)

    def remove_constraint(self, model, constraint):
        if isinstance(constraint, UniqueConstraint) and (
            constraint.condition
            or constraint.contains_expressions
            or constraint.include
            or constraint.deferrable
        ):
            super().remove_constraint(model, constraint)
        else:
            self._remake_table(model)

    def _collate_sql(self, collation):
        return "COLLATE " + collation
