from __future__ import annotations

from plain.postgres import get_connection
from plain.postgres.introspection import (
    ColumnState,
    ConstraintState,
    ConType,
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
        assert "unique_make_model" in state.constraints
        uc = state.constraints["unique_make_model"]
        assert isinstance(uc, ConstraintState)
        assert uc.constraint_type == ConType.UNIQUE
        assert uc.validated is True

    def test_nonexistent_table(self, db):
        """A table that doesn't exist returns TableState(exists=False)."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "this_table_does_not_exist")

        assert state.exists is False
        assert state.columns == {}
        assert state.indexes == {}

    def test_indexes_separated_from_constraints(self, db):
        """Indexes go to state.indexes, constraints go to state.constraints."""
        _execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "examples_car_make_idx" in state.indexes
        idx = state.indexes["examples_car_make_idx"]
        assert isinstance(idx, IndexState)
        assert idx.columns == ["make"]
        assert idx.is_valid is True

        # The unique constraint should be in constraints, not indexes
        assert "unique_make_model" not in state.indexes
        assert "unique_make_model" in state.constraints

    def test_invalid_index(self, db):
        """An index marked INVALID in pg_catalog is reported as is_valid=False."""
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

        assert state.indexes["examples_car_bad_idx"].is_valid is False

    def test_check_constraint(self, db):
        """Check constraints land in state.constraints with contype 'c'."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "car_id_positive" CHECK ("id" > 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "car_id_positive" in state.constraints
        cc = state.constraints["car_id_positive"]
        assert isinstance(cc, ConstraintState)
        assert cc.constraint_type == ConType.CHECK
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

        assert state.constraints["car_id_positive"].validated is False

    def test_foreign_keys(self, db):
        """Foreign keys are in state.constraints with contype 'f' and target info."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_carfeature")

        # CarFeature has FKs to Car and Feature
        fk_constraints = {
            k: v
            for k, v in state.constraints.items()
            if v.constraint_type == ConType.FOREIGN_KEY
        }
        fk_targets = {
            (v.target_table, v.target_column) for v in fk_constraints.values()
        }
        assert ("examples_car", "id") in fk_targets
        assert ("examples_feature", "id") in fk_targets

        # Verify FK structure
        for cs in fk_constraints.values():
            assert isinstance(cs, ConstraintState)
            assert cs.columns  # not empty
            assert cs.target_table is not None
            assert cs.target_column is not None

    def test_primary_key_in_constraints(self, db):
        """Primary key appears in constraints with contype 'p'."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        pk_constraints = {
            k: v
            for k, v in state.constraints.items()
            if v.constraint_type == ConType.PRIMARY
        }
        assert len(pk_constraints) == 1
        pk = next(iter(pk_constraints.values()))
        assert "id" in pk.columns

    def test_exclusion_constraint(self, db):
        """Exclusion constraints land in constraints with contype 'x'."""
        _execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "car_make_excl"'
            ' EXCLUDE USING gist ("make" WITH =)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "car_make_excl" in state.constraints
        xc = state.constraints["car_make_excl"]
        assert xc.constraint_type == ConType.EXCLUSION
        assert xc.validated is True
        assert xc.definition is not None

    def test_hash_index(self, db):
        """Non-btree indexes are stored with their access method."""
        _execute(
            'CREATE INDEX "examples_car_make_hash" ON "examples_car" USING hash ("make")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "examples_car_make_hash" in state.indexes
        idx = state.indexes["examples_car_make_hash"]
        assert idx.access_method == "hash"
        assert idx.is_unique is False
        assert idx.is_valid is True

    def test_unique_index_without_constraint(self, db):
        """A CREATE UNIQUE INDEX (no backing constraint) has is_unique=True."""
        _execute(
            'CREATE UNIQUE INDEX "examples_car_make_uniq_idx"'
            ' ON "examples_car" ("make")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_car")

        assert "examples_car_make_uniq_idx" in state.indexes
        idx = state.indexes["examples_car_make_uniq_idx"]
        assert idx.is_unique is True


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

    def test_strips_type_casts(self):
        """PG adds explicit type casts to stored definitions."""
        assert (
            normalize_check_definition("CHECK (username <> ''::text)")
            == "username <> ''"
        )


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

    def test_with_where_clause(self):
        """normalize_index_definition preserves WHERE clause as-is (structured
        comparison handles WHERE separately)."""
        result = normalize_index_definition(
            "CREATE UNIQUE INDEX foo ON public.bar USING btree (lower(username)) WHERE (NOT (username = ''::text))"
        )
        assert "where" in result
        assert "lower(username)" in result
