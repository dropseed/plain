from plain.models.backends.base.features import BaseDatabaseFeatures


class DatabaseFeatures(BaseDatabaseFeatures):
    minimum_database_version = (12,)
    allows_group_by_selected_pks = True
    can_return_columns_from_insert = True
    can_return_rows_from_bulk_insert = True
    has_native_uuid_field = True
    has_native_duration_field = True
    has_native_json_field = True
    can_defer_constraint_checks = True
    has_select_for_update = True
    has_select_for_update_nowait = True
    has_select_for_update_of = True
    has_select_for_update_skip_locked = True
    has_select_for_no_key_update = True
    supports_comments = True
    supports_transactions = True
    can_rollback_ddl = True
    supports_combined_alters = True
    supports_temporal_subtraction = True
    supports_slicing_ordering_in_compound = True

    requires_casted_case_in_updates = True
    supports_over_clause = True
    only_supports_unbounded_with_preceding_and_following = True
    supports_aggregate_filter_clause = True
    supported_explain_formats = {"JSON", "TEXT", "XML", "YAML"}
    supports_deferrable_unique_constraints = True
    supports_update_conflicts = True
    supports_update_conflicts_with_target = True
    supports_covering_indexes = True
    can_rename_index = True

    supports_unlimited_charfield = True
