from __future__ import annotations

import pytest
from app.examples.models import Car, CarFeature

from plain.postgres import CheckConstraint, Index, Q, UniqueConstraint, get_connection
from plain.postgres.constraints import Deferrable
from plain.postgres.convergence import (
    AddConstraintFix,
    CreateIndexFix,
    DropConstraintFix,
    DropIndexFix,
    RebuildConstraintFix,
    RebuildIndexFix,
    RenameIndexFix,
    ValidateConstraintFix,
    analyze_model,
    detect_fixes,
    detect_model_fixes,
)


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
        """detect_fixes() returns fixes in pass order: rebuild, create indexes,
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
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_extra_check" CHECK ("id" >= 0)'
        )

        try:
            fixes = detect_fixes()
            fix_types = [type(f) for f in fixes]

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
        finally:
            Car.model_options.indexes = original_indexes
            Car.model_options.constraints = original_constraints


class TestDetectConstraintFixes:
    def test_no_fixes_when_converged(self, db):
        conn = get_connection()
        with conn.cursor() as cursor:
            fixes = detect_model_fixes(conn, cursor, Car)
        assert fixes == []

    def test_detects_extra_check_constraint(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            fixes = detect_model_fixes(conn, cursor, Car)

        assert len(fixes) == 1
        fix = fixes[0]
        assert isinstance(fix, DropConstraintFix)
        assert fix.name == "examples_car_test_check"

    def test_detects_extra_unique_constraint(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_extra_unique" UNIQUE ("make")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            fixes = detect_model_fixes(conn, cursor, Car)

        assert len(fixes) == 1
        fix = fixes[0]
        assert isinstance(fix, DropConstraintFix)
        assert fix.name == "examples_car_extra_unique"

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
                fixes = detect_model_fixes(conn, cursor, Car)

            assert len(fixes) == 1
            fix = fixes[0]
            assert isinstance(fix, AddConstraintFix)
            assert fix.constraint.name == "examples_car_id_nonneg"
        finally:
            Car.model_options.constraints = original_constraints

    def test_detects_missing_unique_constraint(self, db):
        _execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')

        conn = get_connection()
        with conn.cursor() as cursor:
            fixes = detect_model_fixes(conn, cursor, Car)

        assert len(fixes) == 1
        fix = fixes[0]
        assert isinstance(fix, AddConstraintFix)
        assert fix.constraint.name == "unique_make_model"

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
                fixes = detect_model_fixes(conn, cursor, Car)

            assert len(fixes) == 1
            fix = fixes[0]
            assert isinstance(fix, ValidateConstraintFix)
            assert fix.name == "examples_car_id_nonneg"
        finally:
            Car.model_options.constraints = original_constraints

    def test_detects_check_constraint_definition_changed(self, db):
        """A check constraint with matching name but different expression is detected."""
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
                fixes = detect_model_fixes(conn, cursor, Car)

            assert len(fixes) == 1
            assert isinstance(fixes[0], RebuildConstraintFix)
            assert fixes[0].constraint.name == "examples_car_id_nonneg"
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
                fixes = detect_model_fixes(conn, cursor, Car)

            assert fixes == []
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
        """Add NOT VALID → validate → fully valid constraint."""
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
                fixes = detect_model_fixes(conn, cursor, Car)
            assert len(fixes) == 1
            assert isinstance(fixes[0], AddConstraintFix)

            fixes[0].apply()
            assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Second converge pass: detects NOT VALID, validates
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert len(fixes) == 1
            assert isinstance(fixes[0], ValidateConstraintFix)

            fixes[0].apply()
            assert _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Third pass: fully converged
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert fixes == []
        finally:
            Car.model_options.constraints = original_constraints

    def test_definition_change_lifecycle(self, isolated_db):
        """Changed check definition: rebuild → validate → converged."""
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

            # First pass: detects definition change → rebuild (drop + add NOT VALID)
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert len(fixes) == 1
            assert isinstance(fixes[0], RebuildConstraintFix)

            fixes[0].apply()

            assert _constraint_exists("examples_car", "examples_car_id_nonneg")
            assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Second pass: NOT VALID → validate
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert len(fixes) == 1
            assert isinstance(fixes[0], ValidateConstraintFix)

            fixes[0].apply()
            assert _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Third pass: fully converged
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert fixes == []
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
                fixes = detect_model_fixes(conn, cursor, Car)

            index_fixes = [f for f in fixes if isinstance(f, CreateIndexFix)]
            assert len(index_fixes) == 1
            assert index_fixes[0].index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_extra_index(self, db):
        """An index in the DB not declared on the model is extra."""
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            fixes = detect_model_fixes(conn, cursor, Car)

        index_fixes = [f for f in fixes if isinstance(f, DropIndexFix)]
        assert len(index_fixes) == 1
        assert index_fixes[0].name == "examples_car_extra_idx"

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
                fixes = detect_model_fixes(conn, cursor, Car)

            rebuild_fixes = [f for f in fixes if isinstance(f, RebuildIndexFix)]
            assert len(rebuild_fixes) == 1
            assert rebuild_fixes[0].index.name == "examples_car_make_idx"
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
                fixes = detect_model_fixes(conn, cursor, Car)

            rebuild_fixes = [f for f in fixes if isinstance(f, RebuildIndexFix)]
            assert len(rebuild_fixes) == 1
            assert rebuild_fixes[0].index.name == "examples_car_make_idx"
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
                fixes = detect_model_fixes(conn, cursor, Car)

            assert fixes == []
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

            rename_fixes = [f for f in analysis.fixes if isinstance(f, RenameIndexFix)]
            assert len(rename_fixes) == 1
            assert rename_fixes[0].old_name == "examples_car_make_old_idx"
            assert rename_fixes[0].new_name == "examples_car_make_new_idx"

            # No separate create or drop
            assert not any(isinstance(f, CreateIndexFix) for f in analysis.fixes)
            assert not any(isinstance(f, DropIndexFix) for f in analysis.fixes)

            # Schema shows the rename as a single index entry
            renamed = [
                idx
                for idx in analysis.indexes
                if idx.name == "examples_car_make_new_idx"
            ]
            assert len(renamed) == 1
            assert renamed[0].issue == "rename from examples_car_make_old_idx"
            assert isinstance(renamed[0].fix, RenameIndexFix)
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

            rename_fixes = [f for f in analysis.fixes if isinstance(f, RenameIndexFix)]
            assert len(rename_fixes) == 1
            assert rename_fixes[0].old_name == "examples_carfeature_car_old_idx"
            assert rename_fixes[0].new_name == "examples_carfeature_car_new_idx"
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

            rename_fixes = [f for f in analysis.fixes if isinstance(f, RenameIndexFix)]
            assert len(rename_fixes) == 1
            assert rename_fixes[0].old_name == "examples_car_make_model_old_idx"
            assert rename_fixes[0].new_name == "examples_car_make_model_new_idx"
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

            assert any(isinstance(f, CreateIndexFix) for f in analysis.fixes)
            assert any(isinstance(f, DropIndexFix) for f in analysis.fixes)
            assert not any(isinstance(f, RenameIndexFix) for f in analysis.fixes)
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

            assert not any(isinstance(f, RenameIndexFix) for f in analysis.fixes)
            create_fixes = [f for f in analysis.fixes if isinstance(f, CreateIndexFix)]
            drop_fixes = [f for f in analysis.fixes if isinstance(f, DropIndexFix)]
            assert len(create_fixes) == 2
            assert len(drop_fixes) == 2
        finally:
            Car.model_options.indexes = original_indexes

    def test_fixable_index_annotated(self, db):
        """A missing index has a fix on its IndexStatus."""
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
            assert isinstance(missing[0].fix, CreateIndexFix)
        finally:
            Car.model_options.indexes = original_indexes

    def test_detect_model_fixes_backward_compat(self, db):
        """detect_model_fixes() still returns list[Fix] correctly."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)

            assert isinstance(fixes, list)
            assert len(fixes) == 1
            assert isinstance(fixes[0], CreateIndexFix)
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
                fixes = detect_model_fixes(conn, cursor, Car)
            assert len(fixes) == 1
            assert isinstance(fixes[0], RenameIndexFix)

            fixes[0].apply()
            assert _index_exists("examples_car_make_new_idx")
            assert not _index_exists("examples_car_make_old_idx")

            # Second pass: converged
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert fixes == []
        finally:
            Car.model_options.indexes = original_indexes
