from __future__ import annotations

from app.examples.models import Car

from plain.postgres import CheckConstraint, Index, Q, get_connection
from plain.postgres.convergence import (
    AddConstraintFix,
    CreateIndexFix,
    DropConstraintFix,
    DropIndexFix,
    RebuildIndexFix,
    ValidateConstraintFix,
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


def _index_exists(name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s",
            [name],
        )
        return cursor.fetchone() is not None


class TestPassOrdering:
    def test_fixes_sorted_by_pass(self, db):
        """detect_fixes() returns fixes in pass order: create indexes, add
        constraints, validate, drop constraints, drop indexes."""
        # Set up a model with a missing index, a missing constraint,
        # an extra index, and an extra constraint
        original_indexes = list(Car.model_options.indexes)
        original_constraints = list(Car.model_options.constraints)

        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_car_id_nonneg"),
        ]

        # Add extras to the DB
        _execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("model")')
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_extra_check" CHECK ("id" >= 0)'
        )

        try:
            fixes = detect_fixes()
            fix_types = [type(f) for f in fixes]

            # All four fix types should be present
            assert CreateIndexFix in fix_types
            assert AddConstraintFix in fix_types
            assert DropConstraintFix in fix_types
            assert DropIndexFix in fix_types

            # Verify pass ordering
            create_idx = max(i for i, t in enumerate(fix_types) if t is CreateIndexFix)
            add_con_min = min(
                i for i, t in enumerate(fix_types) if t is AddConstraintFix
            )
            add_con_max = max(
                i for i, t in enumerate(fix_types) if t is AddConstraintFix
            )
            drop_con_min = min(
                i for i, t in enumerate(fix_types) if t is DropConstraintFix
            )
            drop_con_max = max(
                i for i, t in enumerate(fix_types) if t is DropConstraintFix
            )
            drop_idx = min(i for i, t in enumerate(fix_types) if t is DropIndexFix)

            assert create_idx < add_con_min
            assert add_con_max < drop_con_min
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

    def test_apply_drop_constraint(self, isolated_db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_temp_check" CHECK ("id" >= 0)'
        )
        assert _constraint_exists("examples_car", "examples_car_temp_check")

        fix = DropConstraintFix(table="examples_car", name="examples_car_temp_check")
        fix.apply()

        assert not _constraint_exists("examples_car", "examples_car_temp_check")

    def test_apply_add_unique_constraint(self, isolated_db):
        """Drop a unique constraint, then re-add it via fix."""
        _execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        assert not _constraint_exists("examples_car", "unique_make_model")

        constraint = None
        for c in Car.model_options.constraints:
            if c.name == "unique_make_model":
                constraint = c
                break
        assert constraint is not None

        fix = AddConstraintFix(table="examples_car", constraint=constraint, model=Car)
        fix.apply()

        assert _constraint_exists("examples_car", "unique_make_model")


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


def _create_invalid_index(name: str) -> None:
    """Create a normal index then mark it INVALID via pg_catalog."""
    _execute(f'CREATE INDEX "{name}" ON "examples_car" ("make")')
    _execute(
        f"""
        UPDATE pg_index SET indisvalid = false
        WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = '{name}')
        """
    )


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
            assert rebuild_fixes[0].name == "examples_car_make_idx"
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
                name="examples_car_make_idx",
            )
            sql = fix.apply()

            assert "DROP" in sql
            assert "CONCURRENTLY" in sql
            assert _index_exists("examples_car_make_idx")
            assert _index_is_valid("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes
