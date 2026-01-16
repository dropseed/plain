from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.models.backends.base.base import DatabaseWrapper


class DatabaseFeatures:
    """
    Database features for PostgreSQL.

    Since Plain only supports PostgreSQL, these are the actual PostgreSQL
    capabilities rather than lowest-common-denominator defaults.
    """

    # PostgreSQL 12+ is required
    minimum_database_version: tuple[int, ...] = (12,)

    # PostgreSQL supports GROUP BY on selected primary keys
    allows_group_by_selected_pks = True
    allows_group_by_select_index = True
    empty_fetchmany_value = []
    update_can_self_select = True

    # PostgreSQL supports deferrable unique constraints
    supports_deferrable_unique_constraints = True

    can_use_chunked_reads = True
    # PostgreSQL supports RETURNING clause
    can_return_columns_from_insert = True
    can_return_rows_from_bulk_insert = True
    has_bulk_insert = True
    uses_savepoints = True

    related_fields_match_type = False

    # PostgreSQL has full SELECT FOR UPDATE support
    has_select_for_update = True
    has_select_for_update_nowait = True
    has_select_for_update_skip_locked = True
    has_select_for_update_of = True
    has_select_for_no_key_update = True

    truncates_names = False
    ignores_unnecessary_order_by_in_subqueries = True

    # PostgreSQL has native UUID type
    has_native_uuid_field = True

    # PostgreSQL has native interval type
    has_native_duration_field = True

    # PostgreSQL supports temporal subtraction
    supports_temporal_subtraction = True

    has_zoneinfo_database = True
    order_by_nulls_first = False
    max_query_params = None
    allows_auto_pk_0 = True

    # PostgreSQL can defer constraint checks
    can_defer_constraint_checks = True

    supports_index_column_ordering = True

    # PostgreSQL supports transactional DDL
    can_rollback_ddl = True

    supports_atomic_references_rename = True

    # PostgreSQL can combine ALTER COLUMN clauses
    supports_combined_alters = True

    supports_foreign_keys = True

    # PostgreSQL can rename indexes
    can_rename_index = True

    supports_column_check_constraints = True
    supports_table_check_constraints = True
    can_introspect_check_constraints = True
    bare_select_suffix = ""
    supports_select_for_update_with_limit = True
    ignores_table_name_case = False

    # PostgreSQL supports FILTER clause in aggregates
    supports_aggregate_filter_clause = True

    # PostgreSQL supports window functions
    supports_over_clause = True
    only_supports_unbounded_with_preceding_and_following = True

    supports_callproc_kwargs = False

    # PostgreSQL EXPLAIN formats
    supported_explain_formats = {"JSON", "TEXT", "XML", "YAML"}

    # PostgreSQL requires casted CASE in UPDATE
    requires_casted_case_in_updates = True

    supports_partial_indexes = True
    # PostgreSQL supports covering indexes (INCLUDE)
    supports_covering_indexes = True
    supports_expression_indexes = True
    collate_as_index_expression = False

    supports_comparing_boolean_expr = True

    supports_json_field = True
    can_introspect_json_field = True
    # PostgreSQL has native JSONB type
    has_native_json_field = True
    supports_json_field_contains = True
    has_json_object_function = True

    supports_collation_on_charfield = True
    supports_collation_on_textfield = True

    # PostgreSQL supports COMMENT ON
    supports_comments = True
    supports_comments_inline = False

    supports_logical_xor = False

    # PostgreSQL supports unlimited VARCHAR
    supports_unlimited_charfield = True

    # PostgreSQL always supports transactions
    supports_transactions = True

    def __init__(self, connection: DatabaseWrapper):
        self.connection = connection
