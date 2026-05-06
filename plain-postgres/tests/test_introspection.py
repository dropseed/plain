from __future__ import annotations

from plain.postgres import get_connection
from plain.postgres.introspection import (
    ColumnState,
    ConstraintState,
    ConType,
    IndexState,
    introspect_table,
)


def _execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


class TestIntrospectTable:
    """Boundary tests: introspect_table() against a real Postgres database."""

    def test_existing_table(self, db):
        """Widget table returns a populated TableState with columns and constraints."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert state.exists

        # Columns include id, name, size
        assert "id" in state.columns
        assert "name" in state.columns
        assert "size" in state.columns
        assert isinstance(state.columns["id"], ColumnState)
        assert state.columns["id"].not_null is True
        assert state.columns["name"].not_null is True

        # Has the unique constraint from the model
        assert "unique_widget_name_size" in state.constraints
        uc = state.constraints["unique_widget_name_size"]
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
        _execute(
            'CREATE INDEX "examples_widget_name_idx" ON "examples_widget" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "examples_widget_name_idx" in state.indexes
        idx = state.indexes["examples_widget_name_idx"]
        assert isinstance(idx, IndexState)
        assert idx.columns == ["name"]
        assert idx.is_valid is True

        # The unique constraint should be in constraints, not indexes
        assert "unique_widget_name_size" not in state.indexes
        assert "unique_widget_name_size" in state.constraints

    def test_invalid_index(self, db):
        """An index marked INVALID in pg_catalog is reported as is_valid=False."""
        _execute('CREATE INDEX "examples_widget_bad_idx" ON "examples_widget" ("name")')
        _execute(
            """
            UPDATE pg_index SET indisvalid = false
            WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = 'examples_widget_bad_idx')
            """
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert state.indexes["examples_widget_bad_idx"].is_valid is False

    def test_check_constraint(self, db):
        """Check constraints land in state.constraints with contype 'c'."""
        _execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "widget_id_positive" CHECK ("id" > 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "widget_id_positive" in state.constraints
        cc = state.constraints["widget_id_positive"]
        assert isinstance(cc, ConstraintState)
        assert cc.constraint_type == ConType.CHECK
        assert cc.validated is True
        assert cc.definition is not None
        assert "id" in cc.definition

    def test_not_valid_constraint(self, db):
        """A NOT VALID constraint is reported as validated=False."""
        _execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "widget_id_positive"'
            ' CHECK ("id" > 0) NOT VALID'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert state.constraints["widget_id_positive"].validated is False

    def test_foreign_keys(self, db):
        """Foreign keys are in state.constraints with contype 'f' and target info."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widgettag")

        # WidgetTag has FKs to Widget and Tag
        fk_constraints = {
            k: v
            for k, v in state.constraints.items()
            if v.constraint_type == ConType.FOREIGN_KEY
        }
        fk_targets = {
            (v.target_table, v.target_column) for v in fk_constraints.values()
        }
        assert ("examples_widget", "id") in fk_targets
        assert ("examples_tag", "id") in fk_targets

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
            state = introspect_table(conn, cursor, "examples_widget")

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
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "widget_name_excl"'
            ' EXCLUDE USING gist ("name" WITH =)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "widget_name_excl" in state.constraints
        xc = state.constraints["widget_name_excl"]
        assert xc.constraint_type == ConType.EXCLUSION
        assert xc.validated is True
        assert xc.definition is not None

    def test_hash_index(self, db):
        """Non-btree indexes are stored with their access method."""
        _execute(
            'CREATE INDEX "examples_widget_name_hash" ON "examples_widget" USING hash ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "examples_widget_name_hash" in state.indexes
        idx = state.indexes["examples_widget_name_hash"]
        assert idx.access_method == "hash"
        assert idx.is_unique is False
        assert idx.is_valid is True

    def test_default_btree_index_access_method(self, db):
        """A default-method index is introspected as ``access_method == "btree"``.
        The old introspection collapsed basic btree to ``Index.suffix`` ("idx");
        the rewrite returns the raw ``pg_am.amname`` and updated
        ``MANAGED_INDEX_ACCESS_METHODS`` to match. Pin the contract so a
        partial revert (one side without the other) breaks loudly here
        instead of silently dropping btree indexes from the managed set."""
        _execute(
            'CREATE INDEX "examples_widget_name_btree" ON "examples_widget" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        idx = state.indexes["examples_widget_name_btree"]
        assert idx.access_method == "btree"

    def test_unique_index_without_constraint(self, db):
        """A CREATE UNIQUE INDEX (no backing constraint) has is_unique=True."""
        _execute(
            'CREATE UNIQUE INDEX "examples_widget_name_uniq_idx"'
            ' ON "examples_widget" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "examples_widget_name_uniq_idx" in state.indexes
        idx = state.indexes["examples_widget_name_uniq_idx"]
        assert idx.is_unique is True
