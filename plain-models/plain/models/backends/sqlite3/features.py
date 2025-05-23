import operator
from functools import cached_property

from plain.models import transaction
from plain.models.backends.base.features import BaseDatabaseFeatures
from plain.models.db import OperationalError

from .base import Database


class DatabaseFeatures(BaseDatabaseFeatures):
    minimum_database_version = (3, 21)
    max_query_params = 999
    supports_transactions = True
    can_rollback_ddl = True
    requires_literal_defaults = True
    supports_temporal_subtraction = True
    ignores_table_name_case = True
    # Is "ALTER TABLE ... RENAME COLUMN" supported?
    can_alter_table_rename_column = Database.sqlite_version_info >= (3, 25, 0)
    # Is "ALTER TABLE ... DROP COLUMN" supported?
    can_alter_table_drop_column = Database.sqlite_version_info >= (3, 35, 5)
    supports_parentheses_in_compound = False
    can_defer_constraint_checks = True
    supports_over_clause = Database.sqlite_version_info >= (3, 25, 0)
    supports_aggregate_filter_clause = Database.sqlite_version_info >= (3, 30, 1)
    supports_order_by_nulls_modifier = Database.sqlite_version_info >= (3, 30, 0)
    # NULLS LAST/FIRST emulation on < 3.30 requires subquery wrapping.
    requires_compound_order_by_subquery = Database.sqlite_version_info < (3, 30)
    order_by_nulls_first = True
    supports_json_field_contains = False
    supports_update_conflicts = Database.sqlite_version_info >= (3, 24, 0)
    supports_update_conflicts_with_target = supports_update_conflicts

    @cached_property
    def supports_atomic_references_rename(self):
        return Database.sqlite_version_info >= (3, 26, 0)

    @cached_property
    def supports_json_field(self):
        with self.connection.cursor() as cursor:
            try:
                with transaction.atomic(self.connection.alias):
                    cursor.execute('SELECT JSON(\'{"a": "b"}\')')
            except OperationalError:
                return False
        return True

    can_introspect_json_field = property(operator.attrgetter("supports_json_field"))
    has_json_object_function = property(operator.attrgetter("supports_json_field"))

    @cached_property
    def can_return_columns_from_insert(self):
        return Database.sqlite_version_info >= (3, 35)

    can_return_rows_from_bulk_insert = property(
        operator.attrgetter("can_return_columns_from_insert")
    )
