import operator
from functools import cached_property

from plain.models.backends.base.features import BaseDatabaseFeatures


class DatabaseFeatures(BaseDatabaseFeatures):
    empty_fetchmany_value = ()
    allows_group_by_selected_pks = True
    related_fields_match_type = True
    has_select_for_update = True
    supports_comments = True
    supports_comments_inline = True
    supports_temporal_subtraction = True
    supports_slicing_ordering_in_compound = True
    supports_update_conflicts = True

    # Neither MySQL nor MariaDB support partial indexes.
    supports_partial_indexes = False
    # COLLATE must be wrapped in parentheses because MySQL treats COLLATE as an
    # indexed expression.
    collate_as_index_expression = True

    supports_order_by_nulls_modifier = False
    order_by_nulls_first = True
    supports_logical_xor = True

    @cached_property
    def minimum_database_version(self):
        if self.connection.mysql_is_mariadb:
            return (10, 4)
        else:
            return (8,)

    @cached_property
    def _mysql_storage_engine(self):
        "Internal method used in Plain tests. Don't rely on this from your code"
        return self.connection.mysql_server_data["default_storage_engine"]

    @cached_property
    def allows_auto_pk_0(self):
        """
        Autoincrement primary key can be set to 0 if it doesn't generate new
        autoincrement values.
        """
        return "NO_AUTO_VALUE_ON_ZERO" in self.connection.sql_mode

    @cached_property
    def update_can_self_select(self):
        return self.connection.mysql_is_mariadb and self.connection.mysql_version >= (
            10,
            3,
            2,
        )

    @cached_property
    def can_return_columns_from_insert(self):
        return self.connection.mysql_is_mariadb and self.connection.mysql_version >= (
            10,
            5,
            0,
        )

    can_return_rows_from_bulk_insert = property(
        operator.attrgetter("can_return_columns_from_insert")
    )

    @cached_property
    def has_zoneinfo_database(self):
        return self.connection.mysql_server_data["has_zoneinfo_database"]

    @cached_property
    def is_sql_auto_is_null_enabled(self):
        return self.connection.mysql_server_data["sql_auto_is_null"]

    @cached_property
    def supports_over_clause(self):
        if self.connection.mysql_is_mariadb:
            return True
        return self.connection.mysql_version >= (8, 0, 2)

    @cached_property
    def supports_column_check_constraints(self):
        if self.connection.mysql_is_mariadb:
            return True
        return self.connection.mysql_version >= (8, 0, 16)

    supports_table_check_constraints = property(
        operator.attrgetter("supports_column_check_constraints")
    )

    @cached_property
    def can_introspect_check_constraints(self):
        if self.connection.mysql_is_mariadb:
            return True
        return self.connection.mysql_version >= (8, 0, 16)

    @cached_property
    def has_select_for_update_skip_locked(self):
        if self.connection.mysql_is_mariadb:
            return self.connection.mysql_version >= (10, 6)
        return self.connection.mysql_version >= (8, 0, 1)

    @cached_property
    def has_select_for_update_nowait(self):
        if self.connection.mysql_is_mariadb:
            return True
        return self.connection.mysql_version >= (8, 0, 1)

    @cached_property
    def has_select_for_update_of(self):
        return (
            not self.connection.mysql_is_mariadb
            and self.connection.mysql_version >= (8, 0, 1)
        )

    @cached_property
    def supports_explain_analyze(self):
        return self.connection.mysql_is_mariadb or self.connection.mysql_version >= (
            8,
            0,
            18,
        )

    @cached_property
    def supported_explain_formats(self):
        # Alias MySQL's TRADITIONAL to TEXT for consistency with other
        # backends.
        formats = {"JSON", "TEXT", "TRADITIONAL"}
        if not self.connection.mysql_is_mariadb and self.connection.mysql_version >= (
            8,
            0,
            16,
        ):
            formats.add("TREE")
        return formats

    @cached_property
    def supports_transactions(self):
        """
        All storage engines except MyISAM support transactions.
        """
        return self._mysql_storage_engine != "MyISAM"

    uses_savepoints = property(operator.attrgetter("supports_transactions"))

    @cached_property
    def ignores_table_name_case(self):
        return self.connection.mysql_server_data["lower_case_table_names"]

    @cached_property
    def can_introspect_json_field(self):
        if self.connection.mysql_is_mariadb:
            return self.can_introspect_check_constraints
        return True

    @cached_property
    def supports_index_column_ordering(self):
        if self._mysql_storage_engine != "InnoDB":
            return False
        if self.connection.mysql_is_mariadb:
            return self.connection.mysql_version >= (10, 8)
        return self.connection.mysql_version >= (8, 0, 1)

    @cached_property
    def supports_expression_indexes(self):
        return (
            not self.connection.mysql_is_mariadb
            and self._mysql_storage_engine != "MyISAM"
            and self.connection.mysql_version >= (8, 0, 13)
        )

    @cached_property
    def supports_select_intersection(self):
        is_mariadb = self.connection.mysql_is_mariadb
        return is_mariadb or self.connection.mysql_version >= (8, 0, 31)

    supports_select_difference = property(
        operator.attrgetter("supports_select_intersection")
    )

    @cached_property
    def can_rename_index(self):
        if self.connection.mysql_is_mariadb:
            return self.connection.mysql_version >= (10, 5, 2)
        return True
