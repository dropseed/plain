from __future__ import annotations

from plain.postgres import get_connection
from plain.postgres.introspection import (
    ColumnState,
    ConstraintState,
    ForeignKeyState,
    IndexState,
    introspect_table,
    normalize_check_definition,
    normalize_index_definition,
)


def _execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


class TestIntrospectTable:
    """Boundary tests: introspect_table() against a real Postgres database."""

    def test_existing_table(self, db):
        """Car table returns a populated TableState with columns and constraints."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert state.exists

        # Columns include id, make, model
        assert "id" in state.columns
        assert "make" in state.columns
        assert "model" in state.columns
        assert isinstance(state.columns["id"], ColumnState)
        assert state.columns["id"].not_null is True
        assert state.columns["make"].not_null is True

        # Has the unique constraint from the model
        assert "unique_make_model" in state.unique_constraints
        uc = state.unique_constraints["unique_make_model"]
        assert isinstance(uc, ConstraintState)
        assert uc.validated is True

    def test_nonexistent_table(self, db):
        """A table that doesn't exist returns TableState(exists=False)."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "this_table_does_not_exist")

        assert state.exists is False
        assert state.columns == {}
        assert state.indexes == {}

    def test_indexes_partitioned(self, db):
        """Indexes are correctly separated from constraints."""
        _execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "examples_car_make_idx" in state.indexes
        idx = state.indexes["examples_car_make_idx"]
        assert isinstance(idx, IndexState)
        assert idx.columns == ["make"]
        assert idx.valid is True

        # The unique constraint should NOT appear in indexes
        assert "unique_make_model" not in state.indexes
        assert "unique_make_model" in state.unique_constraints

    def test_invalid_index(self, db):
        """An index marked INVALID in pg_catalog is reported as valid=False."""
        _execute('CREATE INDEX "examples_car_bad_idx" ON "examples_car" ("make")')
        _execute(
            """
            UPDATE pg_index SET indisvalid = false
            WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = 'examples_car_bad_idx')
            """
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert state.indexes["examples_car_bad_idx"].valid is False

    def test_check_constraint(self, db):
        """Check constraints land in check_constraints with their definition."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "car_id_positive" CHECK ("id" > 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "car_id_positive" in state.check_constraints
        cc = state.check_constraints["car_id_positive"]
        assert isinstance(cc, ConstraintState)
        assert cc.validated is True
        assert cc.definition is not None
        assert "id" in cc.definition

    def test_not_valid_constraint(self, db):
        """A NOT VALID constraint is reported as validated=False."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "car_id_positive"'
            ' CHECK ("id" > 0) NOT VALID'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert state.check_constraints["car_id_positive"].validated is False

    def test_foreign_keys(self, db):
        """Foreign keys are extracted with target table and column."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_carfeature")

        # CarFeature has FKs to Car and Feature
        fk_targets = {
            (fk.target_table, fk.target_column) for fk in state.foreign_keys.values()
        }
        assert ("examples_car", "id") in fk_targets
        assert ("examples_feature", "id") in fk_targets

        # Verify FK structure
        for fk in state.foreign_keys.values():
            assert isinstance(fk, ForeignKeyState)
            assert fk.column  # not empty

    def test_primary_key_excluded(self, db):
        """Primary key constraints don't appear in any constraint dict."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        all_constraint_names = (
            set(state.unique_constraints.keys())
            | set(state.check_constraints.keys())
            | set(state.foreign_keys.keys())
            | set(state.indexes.keys())
        )
        # PK index names typically end in _pkey
        assert not any(name.endswith("_pkey") for name in all_constraint_names)


class TestNormalizeCheckDefinition:
    """Unit tests for the pure normalization function."""

    def test_strips_check_wrapper(self):
        assert normalize_check_definition("CHECK (id > 0)") == "id > 0"

    def test_collapses_whitespace(self):
        assert normalize_check_definition("CHECK (id   >   0)") == "id > 0"

    def test_removes_quotes(self):
        assert normalize_check_definition('CHECK ("id" > 0)') == "id > 0"

    def test_strips_redundant_parens(self):
        assert normalize_check_definition("CHECK ((id > 0))") == "id > 0"

    def test_preserves_balanced_inner_parens(self):
        result = normalize_check_definition("CHECK ((a > 0) AND (b > 0))")
        assert "a > 0" in result
        assert "b > 0" in result

    def test_lowercases(self):
        assert normalize_check_definition("CHECK (ID > 0)") == "id > 0"

    def test_handles_bare_expression(self):
        assert normalize_check_definition("id > 0") == "id > 0"


class TestNormalizeIndexDefinition:
    def test_strips_prefix_with_using(self):
        result = normalize_index_definition(
            "CREATE INDEX foo ON bar USING btree (upper(email))"
        )
        assert result == "upper(email)"

    def test_strips_prefix_without_using(self):
        result = normalize_index_definition(
            'CREATE INDEX CONCURRENTLY "foo" ON "bar" (UPPER("email"))'
        )
        assert result == "upper(email)"

    def test_strips_schema_prefix(self):
        result = normalize_index_definition(
            "CREATE INDEX foo ON public.bar USING btree (upper(email))"
        )
        assert result == "upper(email)"

    def test_multi_expression(self):
        result = normalize_index_definition(
            "CREATE INDEX foo ON bar USING btree (lower(name), upper(email))"
        )
        assert result == "lower(name), upper(email)"

    def test_matching_definitions(self):
        """pg_get_indexdef and model-generated SQL normalize to the same string."""
        db_def = "CREATE INDEX foo ON public.bar USING btree (upper(email))"
        model_def = 'CREATE INDEX CONCURRENTLY "new_foo" ON "bar" (UPPER("email"))'
        assert normalize_index_definition(db_def) == normalize_index_definition(
            model_def
        )
