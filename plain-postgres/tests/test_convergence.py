from __future__ import annotations

import pytest
from app.examples.models import Car, CarFeature

from plain.postgres import CheckConstraint, Index, Q, UniqueConstraint, get_connection
from plain.postgres.constraints import Deferrable
from plain.postgres.convergence import (
    AddConstraintFix,
    ConstraintDrift,
    CreateIndexFix,
    DriftKind,
    DropConstraintFix,
    DropIndexFix,
    IndexDrift,
    PlanItem,
    RebuildIndexFix,
    RenameConstraintFix,
    RenameIndexFix,
    ValidateConstraintFix,
    analyze_model,
    can_auto_fix,
    execute_plan,
    plan_convergence,
    plan_model_convergence,
)
from plain.postgres.functions.text import Upper


def _execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


def _constraint_exists(table: str, name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s
            """,
            [table, name],
        )
        return cursor.fetchone() is not None


def _constraint_is_valid(table: str, name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT c.convalidated FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s
            """,
            [table, name],
        )
        row = cursor.fetchone()
        return row[0] if row else False


def _constraint_is_deferrable(table: str, name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT c.condeferrable FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s
            """,
            [table, name],
        )
        row = cursor.fetchone()
        return row[0] if row else False


def _create_invalid_index(name: str) -> None:
    """Create a normal index then mark it INVALID via pg_catalog."""
    _execute(f'CREATE INDEX "{name}" ON "examples_car" ("make")')
    _execute(
        f"""
        UPDATE pg_index SET indisvalid = false
        WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = '{name}')
        """
    )


def _index_exists(name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s",
            [name],
        )
        return cursor.fetchone() is not None


def _index_is_valid(name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT i.indisvalid
            FROM pg_index i
            JOIN pg_class c ON i.indexrelid = c.oid
            WHERE c.relname = %s
            """,
            [name],
        )
        row = cursor.fetchone()
        return row[0] if row else False


class TestPassOrdering:
    def test_fixes_sorted_by_pass(self, db):
        """plan_convergence() returns items in pass order: rebuild, create indexes,
        add constraints, validate, drop constraints, drop indexes."""
        original_indexes = list(Car.model_options.indexes)
        original_constraints = list(Car.model_options.constraints)

        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
            Index(fields=["model"], name="examples_car_model_idx"),
        ]
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_car_id_nonneg"),
            CheckConstraint(check=Q(id__lte=999999), name="examples_car_id_max"),
        ]

        _create_invalid_index("examples_car_model_idx")
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_max"'
            ' CHECK ("id" <= 999999) NOT VALID'
        )
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("model")')
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_extra_check" CHECK ("id" >= -1)'
        )

        try:
            items = plan_convergence().executable(drop_undeclared=True)
            fix_types = [type(item.fix) for item in items]

            # All six fix types should be present
            assert RebuildIndexFix in fix_types
            assert CreateIndexFix in fix_types
            assert AddConstraintFix in fix_types
            assert ValidateConstraintFix in fix_types
            assert DropConstraintFix in fix_types
            assert DropIndexFix in fix_types

            # Verify full pass ordering
            rebuild_idx = max(
                i for i, t in enumerate(fix_types) if t is RebuildIndexFix
            )
            create_idx = max(i for i, t in enumerate(fix_types) if t is CreateIndexFix)
            add_con_max = max(
                i for i, t in enumerate(fix_types) if t is AddConstraintFix
            )
            validate_min = min(
                i for i, t in enumerate(fix_types) if t is ValidateConstraintFix
            )
            validate_max = max(
                i for i, t in enumerate(fix_types) if t is ValidateConstraintFix
            )
            drop_con_min = min(
                i for i, t in enumerate(fix_types) if t is DropConstraintFix
            )
            drop_con_max = max(
                i for i, t in enumerate(fix_types) if t is DropConstraintFix
            )
            drop_idx = min(i for i, t in enumerate(fix_types) if t is DropIndexFix)

            assert rebuild_idx < create_idx
            assert create_idx < add_con_max
            assert add_con_max < validate_min
            assert validate_max < drop_con_min
            assert drop_con_max < drop_idx

            # Without drop_undeclared, drop items should be excluded
            default_items = plan_convergence().executable()
            default_types = [type(item.fix) for item in default_items]
            assert DropConstraintFix not in default_types
            assert DropIndexFix not in default_types
            # Non-drop items should still be present
            assert RebuildIndexFix in default_types
            assert CreateIndexFix in default_types
            assert AddConstraintFix in default_types
            assert ValidateConstraintFix in default_types
        finally:
            Car.model_options.indexes = original_indexes
            Car.model_options.constraints = original_constraints


class TestDetectConstraintFixes:
    def test_no_fixes_when_converged(self, db):
        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()
        assert items == []

    def test_detects_extra_check_constraint_with_prune(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable(
                drop_undeclared=True
            )

        assert len(items) == 1
        assert isinstance(items[0].fix, DropConstraintFix)
        assert items[0].fix.name == "examples_car_test_check"

    def test_extra_check_constraint_excluded_by_default(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()

        assert items == []

    def test_detects_extra_unique_constraint_with_prune(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_extra_unique" UNIQUE ("make")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable(
                drop_undeclared=True
            )

        assert len(items) == 1
        assert isinstance(items[0].fix, DropConstraintFix)
        assert items[0].fix.name == "examples_car_extra_unique"

    def test_extra_unique_constraint_excluded_by_default(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_extra_unique" UNIQUE ("make")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()

        assert items == []

    def test_detects_missing_check_constraint(self, db):
        original_constraints = list(Car.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)
            assert items[0].fix.constraint.name == "examples_car_id_nonneg"
        finally:
            Car.model_options.constraints = original_constraints

    def test_detects_missing_unique_constraint(self, db):
        _execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()

        assert len(items) == 1
        assert isinstance(items[0].fix, AddConstraintFix)
        assert items[0].fix.constraint.name == "unique_make_model"

    def test_detects_not_valid_check_constraint(self, db):
        """A NOT VALID constraint in the DB that matches the model needs validation."""
        original_constraints = list(Car.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]

        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, ValidateConstraintFix)
            assert items[0].fix.name == "examples_car_id_nonneg"
        finally:
            Car.model_options.constraints = original_constraints

    def test_detects_check_constraint_definition_changed(self, db):
        """A check constraint with matching name but different expression is blocked."""
        original_constraints = list(Car.model_options.constraints)
        # Model declares CHECK (id >= 1)
        check = CheckConstraint(
            check=Q(id__gte=1),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]

        # DB has CHECK (id >= 0) — different expression, same name
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            # Changed constraint definition has no auto-fix
            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None
            assert plan.blocked[0].guidance is not None
        finally:
            Car.model_options.constraints = original_constraints

    def test_no_false_positive_for_matching_check_constraint(self, db):
        """A check constraint with matching name and matching expression has no issues."""
        original_constraints = list(Car.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]

        # DB has the same expression
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert items == []
        finally:
            Car.model_options.constraints = original_constraints


class TestApplyConstraintFixes:
    def test_add_check_constraint_uses_not_valid(self, isolated_db):
        """AddConstraintFix for check constraints creates NOT VALID."""
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [*original_constraints, check]

        try:
            fix = AddConstraintFix(table="examples_car", constraint=check, model=Car)
            sql = fix.apply()

            assert "NOT VALID" in sql
            assert _constraint_exists("examples_car", "examples_car_id_nonneg")
            assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")
        finally:
            Car.model_options.constraints = original_constraints

    def test_validate_constraint(self, isolated_db):
        """ValidateConstraintFix validates a NOT VALID constraint."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )
        assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")

        fix = ValidateConstraintFix(table="examples_car", name="examples_car_id_nonneg")
        fix.apply()

        assert _constraint_is_valid("examples_car", "examples_car_id_nonneg")

    def test_full_check_constraint_lifecycle(self, isolated_db):
        """Add NOT VALID -> validate -> fully valid constraint."""
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [*original_constraints, check]

        try:
            # First converge pass: adds NOT VALID
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)

            items[0].fix.apply()
            assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Second converge pass: detects NOT VALID, validates
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, ValidateConstraintFix)

            items[0].fix.apply()
            assert _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Third pass: fully converged
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert items == []
        finally:
            Car.model_options.constraints = original_constraints

    def test_definition_change_is_blocked(self, isolated_db):
        """Changed check definition is blocked — no auto-fix available."""
        original_constraints = list(Car.model_options.constraints)
        # Model declares CHECK (id >= 1)
        check = CheckConstraint(
            check=Q(id__gte=1),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]

        # DB has CHECK (id >= 0) — old expression
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()

            # Detects definition change as blocked (no executable fix)
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None

            # can_auto_fix returns False for changed constraints
            assert not can_auto_fix(plan.blocked[0].drift)
        finally:
            Car.model_options.constraints = original_constraints

    def test_apply_drop_constraint(self, isolated_db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_temp_check" CHECK ("id" >= 0)'
        )
        assert _constraint_exists("examples_car", "examples_car_temp_check")

        fix = DropConstraintFix(table="examples_car", name="examples_car_temp_check")
        fix.apply()

        assert not _constraint_exists("examples_car", "examples_car_temp_check")

    def test_add_unique_using_index(self, isolated_db):
        """Unique constraints use CONCURRENTLY + USING INDEX."""
        # Drop the constraint AND its backing index
        _execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        assert not _constraint_exists("examples_car", "unique_make_model")

        constraint = None
        for c in Car.model_options.constraints:
            if c.name == "unique_make_model":
                constraint = c
                break
        assert constraint is not None

        fix = AddConstraintFix(table="examples_car", constraint=constraint, model=Car)
        sql = fix.apply()

        assert "CONCURRENTLY" in sql
        assert "USING INDEX" in sql
        assert _constraint_exists("examples_car", "unique_make_model")

    @pytest.mark.parametrize(
        "deferrable",
        [Deferrable.DEFERRED, Deferrable.IMMEDIATE],
        ids=["deferred", "immediate"],
    )
    def test_add_deferrable_unique_constraint(self, isolated_db, deferrable):
        """Deferrable unique constraints include the appropriate DEFERRABLE clause."""
        constraint = UniqueConstraint(
            fields=["make"],
            name=f"examples_car_make_{deferrable.value}",
            deferrable=deferrable,
        )
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [*original_constraints, constraint]

        try:
            fix = AddConstraintFix(
                table="examples_car", constraint=constraint, model=Car
            )
            sql = fix.apply()

            assert f"DEFERRABLE INITIALLY {deferrable.name}" in sql
            assert _constraint_exists("examples_car", constraint.name)
            assert _constraint_is_deferrable("examples_car", constraint.name)
        finally:
            Car.model_options.constraints = original_constraints


class TestFixFailureRecovery:
    def test_failed_fix_continues(self, isolated_db):
        """A failed fix rolls back, and the next fix still succeeds."""
        # Add a real constraint to drop
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_real_check" CHECK ("id" >= 0)'
        )
        assert _constraint_exists("examples_car", "examples_car_real_check")

        fixes = [
            # This one will fail — constraint doesn't exist
            DropConstraintFix(table="examples_car", name="nonexistent_constraint"),
            # This one should still succeed
            DropConstraintFix(table="examples_car", name="examples_car_real_check"),
        ]

        results = []
        for fix in fixes:
            try:
                fix.apply()
                results.append("ok")
            except Exception:
                results.append("failed")

        assert results == ["failed", "ok"]
        assert not _constraint_exists("examples_car", "examples_car_real_check")


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
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

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
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

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

        _create_invalid_index("examples_car_make_idx")

        try:
            assert _index_exists("examples_car_make_idx")
            assert not _index_is_valid("examples_car_make_idx")

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
        _execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("model")')

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

    def test_no_false_positive_for_matching_index(self, db):
        """An index with matching name and matching columns produces no issues."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        # DB has index on "make" column — matches the model
        _execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert items == []
        finally:
            Car.model_options.indexes = original_indexes


class TestApplyIndexFixes:
    def test_create_index(self, isolated_db):
        """CreateIndexFix creates an index using CONCURRENTLY."""
        original_indexes = list(Car.model_options.indexes)
        index = Index(fields=["make"], name="examples_car_make_idx")
        Car.model_options.indexes = [*original_indexes, index]

        try:
            assert not _index_exists("examples_car_make_idx")

            fix = CreateIndexFix(table="examples_car", index=index, model=Car)
            sql = fix.apply()

            assert "CONCURRENTLY" in sql
            assert _index_exists("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes

    def test_drop_index(self, isolated_db):
        """DropIndexFix drops an index using CONCURRENTLY."""
        _execute('CREATE INDEX "examples_car_temp_idx" ON "examples_car" ("make")')
        assert _index_exists("examples_car_temp_idx")

        fix = DropIndexFix(table="examples_car", name="examples_car_temp_idx")
        sql = fix.apply()

        assert "CONCURRENTLY" in sql
        assert not _index_exists("examples_car_temp_idx")

    def test_rebuild_invalid_index(self, isolated_db):
        """RebuildIndexFix drops an INVALID index and recreates it."""
        original_indexes = list(Car.model_options.indexes)
        index = Index(fields=["make"], name="examples_car_make_idx")
        Car.model_options.indexes = [*original_indexes, index]

        _create_invalid_index("examples_car_make_idx")

        try:
            assert _index_exists("examples_car_make_idx")
            assert not _index_is_valid("examples_car_make_idx")

            fix = RebuildIndexFix(
                table="examples_car",
                index=index,
                model=Car,
            )
            sql = fix.apply()

            assert "DROP" in sql
            assert "CONCURRENTLY" in sql
            assert _index_exists("examples_car_make_idx")
            assert _index_is_valid("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes


class TestAnalyzeModel:
    """Tests for the unified analysis layer (analyze_model)."""

    def test_rename_detection(self, db):
        """A missing index + extra index with same columns is detected as a rename."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_new_idx"),
        ]
        _execute('CREATE INDEX "examples_car_make_old_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_car_make_old_idx"
            assert rename_drifts[0].new_name == "examples_car_make_new_idx"

            # No separate create or drop drifts
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )

            # Schema shows the rename as a single index entry
            renamed = [
                idx
                for idx in analysis.indexes
                if idx.name == "examples_car_make_new_idx"
            ]
            assert len(renamed) == 1
            assert renamed[0].issue == "rename from examples_car_make_old_idx"
            assert renamed[0].drift is not None
            assert renamed[0].drift.kind == DriftKind.RENAMED
        finally:
            Car.model_options.indexes = original_indexes

    def test_rename_with_fk_columns(self, db):
        """Rename detection resolves model field names to DB column names."""
        original_indexes = list(CarFeature.model_options.indexes)
        # Model field is "car", DB column is "car_id"
        CarFeature.model_options.indexes = [
            *original_indexes,
            Index(fields=["car"], name="examples_carfeature_car_new_idx"),
        ]
        _execute(
            'CREATE INDEX "examples_carfeature_car_old_idx"'
            ' ON "examples_carfeature" ("car_id")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, CarFeature)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_carfeature_car_old_idx"
            assert rename_drifts[0].new_name == "examples_carfeature_car_new_idx"
        finally:
            CarFeature.model_options.indexes = original_indexes

    def test_rename_multi_column(self, db):
        """Rename detection works for multi-column indexes."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make", "model"], name="examples_car_make_model_new_idx"),
        ]
        _execute(
            'CREATE INDEX "examples_car_make_model_old_idx"'
            ' ON "examples_car" ("make", "model")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_car_make_model_old_idx"
            assert rename_drifts[0].new_name == "examples_car_make_model_new_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_rename_when_columns_differ(self, db):
        """Different columns means separate create + drop, not a rename."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["model"], name="examples_car_model_idx"),
        ]
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            assert any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
                for d in analysis.drifts
            )
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_rename_when_ambiguous(self, db):
        """Two missing + two extra with same columns: no rename, all create/drop."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_idx_a"),
            Index(fields=["make"], name="examples_car_idx_b"),
        ]
        _execute('CREATE INDEX "examples_car_old_a" ON "examples_car" ("make")')
        _execute('CREATE INDEX "examples_car_old_b" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
                for d in analysis.drifts
            )
            missing_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
            ]
            undeclared_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
            ]
            assert len(missing_drifts) == 2
            assert len(undeclared_drifts) == 2
        finally:
            Car.model_options.indexes = original_indexes

    def test_rename_expression_index(self, db):
        """Expression-based indexes are matched by normalized definition."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(Upper("make"), name="examples_car_make_upper_new_idx"),
        ]
        _execute(
            'CREATE INDEX "examples_car_make_upper_old_idx"'
            ' ON "examples_car" (UPPER("make"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_car_make_upper_old_idx"
            assert rename_drifts[0].new_name == "examples_car_make_upper_new_idx"

            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
        finally:
            Car.model_options.indexes = original_indexes

    def test_fixable_index_annotated(self, db):
        """A missing index has a drift on its IndexStatus."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            missing = [
                idx for idx in analysis.indexes if idx.name == "examples_car_make_idx"
            ]
            assert len(missing) == 1
            assert missing[0].issue is not None
            assert missing[0].drift is not None
            assert missing[0].drift.kind == DriftKind.MISSING
        finally:
            Car.model_options.indexes = original_indexes

    def test_plan_model_convergence(self, db):
        """plan_model_convergence() returns a plan with correct items."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert isinstance(items, list)
            assert len(items) == 1
            assert isinstance(items[0].fix, CreateIndexFix)
        finally:
            Car.model_options.indexes = original_indexes

    def test_issue_count(self, db):
        """ModelAnalysis.issue_count counts issues correctly."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            # Missing index = 1 issue
            assert analysis.issue_count >= 1
            missing = [
                idx for idx in analysis.indexes if idx.name == "examples_car_make_idx"
            ]
            assert len(missing) == 1
            assert missing[0].issue is not None
        finally:
            Car.model_options.indexes = original_indexes


class TestApplyRenameIndex:
    def test_rename_index(self, isolated_db):
        """RenameIndexFix renames using ALTER INDEX ... RENAME TO."""
        _execute('CREATE INDEX "examples_car_old_idx" ON "examples_car" ("make")')
        assert _index_exists("examples_car_old_idx")

        fix = RenameIndexFix(
            table="examples_car",
            old_name="examples_car_old_idx",
            new_name="examples_car_new_idx",
        )
        sql = fix.apply()

        assert "RENAME TO" in sql
        assert not _index_exists("examples_car_old_idx")
        assert _index_exists("examples_car_new_idx")

    def test_rename_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_new_idx"),
        ]
        _execute('CREATE INDEX "examples_car_make_old_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()

            # First pass: detect rename
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, RenameIndexFix)

            items[0].fix.apply()
            assert _index_exists("examples_car_make_new_idx")
            assert not _index_exists("examples_car_make_old_idx")

            # Second pass: converged
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert items == []
        finally:
            Car.model_options.indexes = original_indexes


class TestConstraintRename:
    def test_rename_check_constraint(self, db):
        """A missing + extra check constraint with same expression is a rename."""
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_car_id_new"),
        ]
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_old"'
            ' CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, ConstraintDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_car_id_old"
            assert rename_drifts[0].new_name == "examples_car_id_new"

            assert not any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
        finally:
            Car.model_options.constraints = original_constraints

    def test_rename_unique_constraint(self, db):
        """A missing + extra unique constraint with same columns is a rename."""
        _execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "old_unique_make_model"'
            ' UNIQUE ("make", "model")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, Car)

        rename_drifts = [
            d
            for d in analysis.drifts
            if isinstance(d, ConstraintDrift) and d.kind == DriftKind.RENAMED
        ]
        assert len(rename_drifts) == 1
        assert rename_drifts[0].old_name == "old_unique_make_model"
        assert rename_drifts[0].new_name == "unique_make_model"

    def test_no_rename_when_expression_differs(self, db):
        """Different check expressions means separate add + drop, not rename."""
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=1), name="examples_car_id_new"),
        ]
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_old"'
            ' CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            assert not any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.RENAMED
                for d in analysis.drifts
            )
            assert any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
        finally:
            Car.model_options.constraints = original_constraints

    def test_apply_rename_constraint(self, isolated_db):
        """RenameConstraintFix renames using ALTER TABLE RENAME CONSTRAINT."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "old_check" CHECK ("id" >= 0)'
        )
        assert _constraint_exists("examples_car", "old_check")

        fix = RenameConstraintFix(
            table="examples_car",
            old_name="old_check",
            new_name="new_check",
        )
        sql = fix.apply()

        assert "RENAME CONSTRAINT" in sql
        assert not _constraint_exists("examples_car", "old_check")
        assert _constraint_exists("examples_car", "new_check")

    def test_rename_unique_renames_backing_index(self, isolated_db):
        """Renaming a unique constraint also renames its backing index."""
        _execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "old_unique"'
            ' UNIQUE ("make", "model")'
        )
        assert _constraint_exists("examples_car", "old_unique")
        assert _index_exists("old_unique")

        fix = RenameConstraintFix(
            table="examples_car",
            old_name="old_unique",
            new_name="new_unique",
        )
        fix.apply()

        assert _constraint_exists("examples_car", "new_unique")
        assert _index_exists("new_unique")
        assert not _constraint_exists("examples_car", "old_unique")
        assert not _index_exists("old_unique")

    def test_rename_constraint_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_car_id_new"),
        ]
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_old"'
            ' CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()

            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, RenameConstraintFix)

            items[0].fix.apply()

            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert items == []
        finally:
            Car.model_options.constraints = original_constraints


class TestDriftPolicy:
    """Tests for blocks_sync and DriftKind policy via PlanItem."""

    def test_index_fixes_do_not_block_sync(self, db):
        """Index operations (create, rebuild, rename) do not block sync."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, CreateIndexFix)
            assert items[0].blocks_sync is False
        finally:
            Car.model_options.indexes = original_indexes

    def test_constraint_add_blocks_sync(self, db):
        """Adding a missing constraint blocks sync."""
        original_constraints = list(Car.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)
            assert items[0].blocks_sync is True
        finally:
            Car.model_options.constraints = original_constraints

    def test_constraint_validate_blocks_sync(self, db):
        """Validating a NOT VALID constraint blocks sync."""
        original_constraints = list(Car.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, ValidateConstraintFix)
            assert items[0].blocks_sync is True
        finally:
            Car.model_options.constraints = original_constraints

    def test_rename_does_not_block_sync(self, db):
        """Renames (index and constraint) do not block sync."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_new_idx"),
        ]
        _execute('CREATE INDEX "examples_car_make_old_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, RenameIndexFix)
            assert items[0].blocks_sync is False
        finally:
            Car.model_options.indexes = original_indexes

    def test_undeclared_constraint_is_blocking_cleanup(self, db):
        """Undeclared constraints are drop_undeclared + blocks_sync."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        plan = plan_convergence()
        undeclared = [
            item
            for item in plan.items
            if isinstance(item.drift, ConstraintDrift)
            and item.drift.kind == DriftKind.UNDECLARED
        ]
        assert len(undeclared) == 1
        assert undeclared[0].drop_undeclared is True
        assert undeclared[0].blocks_sync is True

    def test_undeclared_index_is_optional_cleanup(self, db):
        """Undeclared indexes are drop_undeclared + not blocks_sync."""
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        plan = plan_convergence()
        undeclared = [
            item
            for item in plan.items
            if isinstance(item.drift, IndexDrift)
            and item.drift.kind == DriftKind.UNDECLARED
        ]
        assert len(undeclared) == 1
        assert undeclared[0].drop_undeclared is True
        assert undeclared[0].blocks_sync is False

    def test_can_auto_fix_for_missing(self, db):
        """can_auto_fix returns True for missing indexes and constraints."""
        assert can_auto_fix(IndexDrift(kind=DriftKind.MISSING, table="t"))
        assert can_auto_fix(ConstraintDrift(kind=DriftKind.MISSING, table="t"))

    def test_can_auto_fix_false_for_changed_constraint(self):
        """can_auto_fix returns False for changed constraint definitions."""
        drift = ConstraintDrift(kind=DriftKind.CHANGED, table="t")
        assert not can_auto_fix(drift)


class TestConvergencePlan:
    def test_executable_excludes_cleanup_by_default(self, db):
        """Default mode excludes cleanup items."""
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        plan = plan_convergence()
        default = plan.executable()
        with_drop = plan.executable(drop_undeclared=True)

        drop_in_default = [
            item for item in default if isinstance(item.fix, DropIndexFix)
        ]
        drop_in_drop = [
            item for item in with_drop if isinstance(item.fix, DropIndexFix)
        ]
        assert drop_in_default == []
        assert len(drop_in_drop) == 1

    def test_has_work_ignores_cleanup_by_default(self, db):
        """has_work() only counts cleanup items when drop_undeclared=True."""
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        plan = plan_convergence()
        assert not plan.has_work()
        assert plan.has_work(drop_undeclared=True)

    def test_has_work_counts_forward_fixes(self, db):
        """has_work() sees forward fixes regardless of drop_undeclared."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            plan = plan_convergence()
            assert plan.has_work()
            assert plan.has_work(drop_undeclared=True)
        finally:
            Car.model_options.indexes = original_indexes

    def test_blocking_cleanup_for_extra_constraint(self, db):
        """Extra constraint is blocking cleanup."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        plan = plan_convergence()
        assert len(plan.blocking_cleanup) == 1
        assert (
            plan.blocking_cleanup[0].describe()
            == "examples_car: drop constraint examples_car_test_check"
        )
        assert plan.optional_cleanup == []

    def test_optional_cleanup_for_extra_index(self, db):
        """Extra index is optional cleanup."""
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        plan = plan_convergence()
        assert plan.blocking_cleanup == []
        assert len(plan.optional_cleanup) == 1
        assert (
            plan.optional_cleanup[0].describe()
            == "examples_car: drop index examples_car_extra_idx"
        )

    def test_blocking_and_optional_together(self, db):
        """Both blocking and optional cleanup can coexist."""
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        plan = plan_convergence()
        assert len(plan.blocking_cleanup) == 1
        assert len(plan.optional_cleanup) == 1

    def test_no_cleanup_when_converged(self, db):
        """Fully converged schema has no cleanup."""
        plan = plan_convergence()
        assert plan.blocking_cleanup == []
        assert plan.optional_cleanup == []

    def test_blocked_for_changed_constraint(self, db):
        """Changed constraint definition appears in plan.blocked."""
        original_constraints = list(Car.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=1),
            name="examples_car_id_nonneg",
        )
        Car.model_options.constraints = [*original_constraints, check]
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert len(plan.blocked) == 1
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None
            assert plan.blocked[0].guidance is not None
        finally:
            Car.model_options.constraints = original_constraints


class TestExecutePlan:
    def test_collects_results(self, isolated_db):
        """execute_plan() collects SQL from successful items."""
        _execute('CREATE INDEX "examples_car_temp_idx" ON "examples_car" ("make")')
        fix = DropIndexFix(table="examples_car", name="examples_car_temp_idx")
        drift = IndexDrift(
            kind=DriftKind.UNDECLARED,
            table="examples_car",
            name="examples_car_temp_idx",
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=False, drop_undeclared=True)

        result = execute_plan([item])

        assert result.applied == 1
        assert result.failed == 0
        assert result.ok
        assert len(result.results) == 1
        assert result.results[0].ok
        assert "examples_car_temp_idx" in (result.results[0].sql or "")

    def test_handles_failure(self, isolated_db):
        """execute_plan() captures errors without raising."""
        fix = DropConstraintFix(table="examples_car", name="nonexistent")
        drift = ConstraintDrift(
            kind=DriftKind.UNDECLARED, table="examples_car", name="nonexistent"
        )
        item = PlanItem(drift=drift, fix=fix, drop_undeclared=True)

        result = execute_plan([item])

        assert result.applied == 0
        assert result.failed == 1
        assert not result.ok
        assert result.results[0].error is not None

    def test_continues_after_failure(self, isolated_db):
        """A failed item doesn't block subsequent items."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_real_check" CHECK ("id" >= 0)'
        )

        items = [
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED, table="examples_car", name="nonexistent"
                ),
                fix=DropConstraintFix(table="examples_car", name="nonexistent"),
                drop_undeclared=True,
            ),
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_car",
                    name="examples_car_real_check",
                ),
                fix=DropConstraintFix(
                    table="examples_car", name="examples_car_real_check"
                ),
                drop_undeclared=True,
            ),
        ]

        result = execute_plan(items)

        assert result.applied == 1
        assert result.failed == 1
        assert not _constraint_exists("examples_car", "examples_car_real_check")

    def test_summary(self, isolated_db):
        """ConvergenceResult.summary formats correctly."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_real_check" CHECK ("id" >= 0)'
        )

        items = [
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED, table="examples_car", name="nonexistent"
                ),
                fix=DropConstraintFix(table="examples_car", name="nonexistent"),
                drop_undeclared=True,
            ),
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_car",
                    name="examples_car_real_check",
                ),
                fix=DropConstraintFix(
                    table="examples_car", name="examples_car_real_check"
                ),
                drop_undeclared=True,
            ),
        ]

        result = execute_plan(items)

        assert result.summary == "1 applied, 1 failed."

    def test_result_item_reference(self, isolated_db):
        """FixResult.item references the PlanItem."""
        _execute('CREATE INDEX "examples_car_temp_idx" ON "examples_car" ("make")')
        fix = DropIndexFix(table="examples_car", name="examples_car_temp_idx")
        drift = IndexDrift(
            kind=DriftKind.UNDECLARED,
            table="examples_car",
            name="examples_car_temp_idx",
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=False, drop_undeclared=True)

        result = execute_plan([item])

        assert result.results[0].item is item


class TestSyncPolicy:
    """Tests for blocks_sync and ok_for_sync semantics."""

    def test_blocking_failure_fails_sync(self, isolated_db):
        """A failed constraint fix (blocks_sync=True) makes ok_for_sync False."""
        fix = DropConstraintFix(table="examples_car", name="nonexistent")
        drift = ConstraintDrift(
            kind=DriftKind.UNDECLARED, table="examples_car", name="nonexistent"
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=True, drop_undeclared=True)

        result = execute_plan([item])

        assert not result.ok
        assert not result.ok_for_sync
        assert len(result.blocking_failures) == 1
        assert result.non_blocking_failures == []

    def test_non_blocking_failure_passes_sync(self, isolated_db):
        """A failed index fix (blocks_sync=False) keeps ok_for_sync True."""
        fix = CreateIndexFix(
            table="examples_car",
            index=Index(fields=["make"], name="examples_car_will_fail_idx"),
            model=Car,
        )
        drift = IndexDrift(
            kind=DriftKind.MISSING, table="examples_car", index=fix.index, model=Car
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=False)

        # Create it first so the CONCURRENTLY create will fail (duplicate)
        _execute('CREATE INDEX "examples_car_will_fail_idx" ON "examples_car" ("make")')

        result = execute_plan([item])

        assert not result.ok
        assert result.ok_for_sync
        assert result.blocking_failures == []
        assert len(result.non_blocking_failures) == 1

    def test_mixed_failures(self, isolated_db):
        """Blocking + non-blocking failures: ok_for_sync reflects only blocking."""
        _execute('CREATE INDEX "examples_car_will_fail_idx" ON "examples_car" ("make")')

        index = Index(fields=["make"], name="examples_car_will_fail_idx")
        items = [
            # Non-blocking: will fail (duplicate index)
            PlanItem(
                drift=IndexDrift(
                    kind=DriftKind.MISSING, table="examples_car", index=index, model=Car
                ),
                fix=CreateIndexFix(table="examples_car", index=index, model=Car),
                blocks_sync=False,
            ),
            # Blocking: will fail (nonexistent constraint)
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED, table="examples_car", name="nonexistent"
                ),
                fix=DropConstraintFix(table="examples_car", name="nonexistent"),
                blocks_sync=True,
                drop_undeclared=True,
            ),
        ]

        result = execute_plan(items)

        assert not result.ok
        assert not result.ok_for_sync
        assert len(result.blocking_failures) == 1
        assert len(result.non_blocking_failures) == 1

    def test_all_success_passes_sync(self, isolated_db):
        """All items succeeding means ok_for_sync is True."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_temp" CHECK ("id" >= 0)'
        )
        fix = DropConstraintFix(table="examples_car", name="examples_car_temp")
        drift = ConstraintDrift(
            kind=DriftKind.UNDECLARED, table="examples_car", name="examples_car_temp"
        )
        item = PlanItem(drift=drift, fix=fix, drop_undeclared=True)

        result = execute_plan([item])

        assert result.ok
        assert result.ok_for_sync

    def test_empty_result_passes_sync(self):
        """No items executed means ok_for_sync is True."""
        result = execute_plan([])
        assert result.ok_for_sync
