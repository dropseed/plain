from __future__ import annotations

from app.examples.models import Car
from conftest_convergence import (
    create_invalid_index,
    execute,
    index_exists,
    index_is_valid,
)

from plain.postgres import Index, Q, get_connection
from plain.postgres.convergence import (
    CreateIndexFix,
    DropIndexFix,
    RebuildIndexFix,
    RenameIndexFix,
    plan_model_convergence,
)
from plain.postgres.convergence.analysis import DriftKind, IndexDrift, analyze_model
from plain.postgres.functions.text import Upper


def _create_hash_index(name: str = "examples_car_make_hash_idx") -> None:
    execute(f'CREATE INDEX "{name}" ON "examples_car" USING hash ("make")')


class TestUnmanagedIndexTypes:
    def test_hash_index_not_flagged_as_undeclared(self, db):
        """A hash index is unmanaged — no drift, shown as informational."""
        _create_hash_index()

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, Car)

        # No drift for the hash index
        assert not any(
            isinstance(d, IndexDrift)
            and getattr(d, "name", None) == "examples_car_make_hash_idx"
            for d in analysis.drifts
        )

        # Appears in indexes with access_method set (informational)
        hash_idx = next(
            idx for idx in analysis.indexes if idx.name == "examples_car_make_hash_idx"
        )
        assert hash_idx.access_method == "hash"
        assert hash_idx.issue is None
        assert hash_idx.drift is None

    def test_unmanaged_index_not_dropped_by_drop_undeclared(self, db):
        """--drop-undeclared does not propose dropping unmanaged index types."""
        _create_hash_index()

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable(
                drop_undeclared=True
            )

        assert not any(
            isinstance(item.fix, DropIndexFix)
            and item.fix.name == "examples_car_make_hash_idx"
            for item in items
        )

    def test_btree_extra_index_still_undeclared(self, db):
        """A btree index not in the model is still flagged as undeclared."""
        execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, Car)

        assert any(
            isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
            for d in analysis.drifts
        )

    def test_unmanaged_index_not_counted_as_issue(self, db):
        """Unmanaged indexes don't count toward the issue total."""
        _create_hash_index()

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, Car)

        assert analysis.issue_count == 0

    def test_name_conflict_with_unmanaged_index(self, db):
        """A declared index whose name collides with a hash index is an error."""
        _create_hash_index("examples_car_make_idx")

        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            conflict = next(
                idx
                for idx in analysis.indexes
                if idx.name == "examples_car_make_idx" and idx.issue
            )
            assert conflict.issue is not None
            assert "name conflict" in conflict.issue
            assert "hash" in conflict.issue
            assert conflict.drift is None  # no auto-fix
        finally:
            Car.model_options.indexes = original_indexes


class TestDetectIndexFixes:
    def test_detects_missing_index(self, db):
        """Add an index to the model, detect it as missing."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            index_items = [
                item for item in items if isinstance(item.fix, CreateIndexFix)
            ]
            assert len(index_items) == 1
            assert isinstance(index_items[0].fix, CreateIndexFix)
            assert index_items[0].fix.index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_extra_index_with_prune(self, db):
        """An index in the DB not declared on the model is extra (requires prune)."""
        execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable(
                drop_undeclared=True
            )

        index_items = [item for item in items if isinstance(item.fix, DropIndexFix)]
        assert len(index_items) == 1
        fix = index_items[0].fix
        assert isinstance(fix, DropIndexFix)
        assert fix.name == "examples_car_extra_idx"

    def test_extra_index_excluded_by_default(self, db):
        """An extra index produces no item by default."""
        execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()

        assert items == []

    def test_detects_invalid_index(self, isolated_db):
        """An INVALID index matching a model index produces a RebuildIndexFix."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        create_invalid_index("examples_car_make_idx")

        try:
            assert index_exists("examples_car_make_idx")
            assert not index_is_valid("examples_car_make_idx")

            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            rebuild_items = [
                item for item in items if isinstance(item.fix, RebuildIndexFix)
            ]
            assert len(rebuild_items) == 1
            fix = rebuild_items[0].fix
            assert isinstance(fix, RebuildIndexFix)
            assert fix.index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_index_definition_changed(self, db):
        """An index with the same name but different columns produces a RebuildIndexFix."""
        original_indexes = list(Car.model_options.indexes)
        # Model declares index on "make" field
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        # DB has index on "model" column instead
        execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("model")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            rebuild_items = [
                item for item in items if isinstance(item.fix, RebuildIndexFix)
            ]
            assert len(rebuild_items) == 1
            fix = rebuild_items[0].fix
            assert isinstance(fix, RebuildIndexFix)
            assert fix.index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_expression_index_definition_changed(self, db):
        """An expression index with the same name but different expression produces a RebuildIndexFix."""
        original_indexes = list(Car.model_options.indexes)
        # Model declares UPPER(make)
        Car.model_options.indexes = [
            *original_indexes,
            Index(Upper("make"), name="examples_car_make_expr_idx"),
        ]

        # DB has LOWER(make) under the same name
        execute(
            'CREATE INDEX "examples_car_make_expr_idx"'
            ' ON "examples_car" (LOWER("make"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            rebuild_items = [
                item for item in items if isinstance(item.fix, RebuildIndexFix)
            ]
            assert len(rebuild_items) == 1
            fix = rebuild_items[0].fix
            assert isinstance(fix, RebuildIndexFix)
            assert fix.index.name == "examples_car_make_expr_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_expression_index(self, db):
        """An expression index with matching name and definition produces no issues."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(Upper("make"), name="examples_car_make_expr_idx"),
        ]

        # DB has the same expression
        execute(
            'CREATE INDEX "examples_car_make_expr_idx"'
            ' ON "examples_car" (UPPER("make"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert items == []
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_index(self, db):
        """An index with matching name and matching columns produces no issues."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        # DB has index on "make" column — matches the model
        execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert items == []
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_partial_index_condition_changed(self, db):
        """A partial index with same name/columns but different WHERE produces a RebuildIndexFix."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["make"],
                condition=Q(id__gt=100),
                name="examples_car_make_partial_idx",
            ),
        ]

        # DB has partial index on same column but different condition
        execute(
            'CREATE INDEX "examples_car_make_partial_idx"'
            ' ON "examples_car" ("make") WHERE ("id" > 50)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            rebuild_items = [
                item for item in items if isinstance(item.fix, RebuildIndexFix)
            ]
            assert len(rebuild_items) == 1
            fix = rebuild_items[0].fix
            assert isinstance(fix, RebuildIndexFix)
            assert fix.index.name == "examples_car_make_partial_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_partial_index(self, db):
        """A partial index with matching name, columns, and condition produces no issues."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["make"],
                condition=Q(id__gt=100),
                name="examples_car_make_partial_idx",
            ),
        ]

        # DB has the matching partial index
        execute(
            'CREATE INDEX "examples_car_make_partial_idx"'
            ' ON "examples_car" ("make") WHERE ("id" > 100)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert items == []
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_false_rename_when_condition_differs(self, db):
        """Two indexes on same column but different conditions should not be detected as a rename."""
        original_indexes = list(Car.model_options.indexes)
        # Model has a partial index with a condition
        Car.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["make"],
                condition=Q(id__gt=100),
                name="examples_car_make_new_idx",
            ),
        ]

        # DB has an index on same column but no condition, under a different name
        execute('CREATE INDEX "examples_car_make_old_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            # Should NOT be a rename — definitions differ
            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 0

            # Should be a missing + undeclared instead
            missing = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
            ]
            assert len(missing) == 1
            assert missing[0].index is not None
            assert missing[0].index.name == "examples_car_make_new_idx"
        finally:
            Car.model_options.indexes = original_indexes


class TestApplyIndexFixes:
    def test_create_index(self, isolated_db):
        """CreateIndexFix creates an index using CONCURRENTLY."""
        original_indexes = list(Car.model_options.indexes)
        index = Index(fields=["make"], name="examples_car_make_idx")
        Car.model_options.indexes = [*original_indexes, index]

        try:
            assert not index_exists("examples_car_make_idx")

            fix = CreateIndexFix(table="examples_car", index=index, model=Car)
            sql = fix.apply()

            assert "CONCURRENTLY" in sql
            assert index_exists("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes

    def test_drop_index(self, isolated_db):
        """DropIndexFix drops an index using CONCURRENTLY."""
        execute('CREATE INDEX "examples_car_temp_idx" ON "examples_car" ("make")')
        assert index_exists("examples_car_temp_idx")

        fix = DropIndexFix(table="examples_car", name="examples_car_temp_idx")
        sql = fix.apply()

        assert "CONCURRENTLY" in sql
        assert not index_exists("examples_car_temp_idx")

    def test_rebuild_invalid_index(self, isolated_db):
        """RebuildIndexFix drops an INVALID index and recreates it."""
        original_indexes = list(Car.model_options.indexes)
        index = Index(fields=["make"], name="examples_car_make_idx")
        Car.model_options.indexes = [*original_indexes, index]

        create_invalid_index("examples_car_make_idx")

        try:
            assert index_exists("examples_car_make_idx")
            assert not index_is_valid("examples_car_make_idx")

            fix = RebuildIndexFix(
                table="examples_car",
                index=index,
                model=Car,
            )
            sql = fix.apply()

            assert "DROP" in sql
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_car_make_idx")
            assert index_is_valid("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes


class TestApplyRenameIndex:
    def test_rename_index(self, isolated_db):
        """RenameIndexFix renames using ALTER INDEX ... RENAME TO."""
        execute('CREATE INDEX "examples_car_old_idx" ON "examples_car" ("make")')
        assert index_exists("examples_car_old_idx")

        fix = RenameIndexFix(
            table="examples_car",
            old_name="examples_car_old_idx",
            new_name="examples_car_new_idx",
        )
        sql = fix.apply()

        assert "RENAME TO" in sql
        assert not index_exists("examples_car_old_idx")
        assert index_exists("examples_car_new_idx")

    def test_rename_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_new_idx"),
        ]
        execute('CREATE INDEX "examples_car_make_old_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()

            # First pass: detect rename
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, RenameIndexFix)

            items[0].fix.apply()
            assert index_exists("examples_car_make_new_idx")
            assert not index_exists("examples_car_make_old_idx")

            # Second pass: converged
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert items == []
        finally:
            Car.model_options.indexes = original_indexes
