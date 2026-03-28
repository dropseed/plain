from __future__ import annotations

from app.examples.models import Car

from plain.postgres import CheckConstraint, Q, get_connection
from plain.postgres.convergence import (
    AddConstraintFix,
    DropConstraintFix,
    ValidateConstraintFix,
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

        # Create the constraint as NOT VALID
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
    def test_add_check_constraint_uses_not_valid(self, db):
        """AddConstraintFix for check constraints creates NOT VALID."""
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_car_id_nonneg",
        )
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [*original_constraints, check]

        try:
            fix = AddConstraintFix(table="examples_car", constraint=check, model=Car)
            with get_connection().cursor() as cursor:
                sql = fix.apply(cursor)

            assert "NOT VALID" in sql
            assert _constraint_exists("examples_car", "examples_car_id_nonneg")
            assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")
        finally:
            Car.model_options.constraints = original_constraints

    def test_validate_constraint(self, db):
        """ValidateConstraintFix validates a NOT VALID constraint."""
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )
        assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")

        fix = ValidateConstraintFix(table="examples_car", name="examples_car_id_nonneg")
        with get_connection().cursor() as cursor:
            fix.apply(cursor)

        assert _constraint_is_valid("examples_car", "examples_car_id_nonneg")

    def test_full_check_constraint_lifecycle(self, db):
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

            with get_connection().cursor() as cursor:
                fixes[0].apply(cursor)

            assert not _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Second converge pass: detects NOT VALID, validates
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert len(fixes) == 1
            assert isinstance(fixes[0], ValidateConstraintFix)

            with get_connection().cursor() as cursor:
                fixes[0].apply(cursor)

            assert _constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Third pass: fully converged
            with conn.cursor() as cursor:
                fixes = detect_model_fixes(conn, cursor, Car)
            assert fixes == []
        finally:
            Car.model_options.constraints = original_constraints

    def test_apply_drop_constraint(self, db):
        _execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_temp_check" CHECK ("id" >= 0)'
        )
        assert _constraint_exists("examples_car", "examples_car_temp_check")

        fix = DropConstraintFix(table="examples_car", name="examples_car_temp_check")
        with get_connection().cursor() as cursor:
            fix.apply(cursor)

        assert not _constraint_exists("examples_car", "examples_car_temp_check")

    def test_apply_add_unique_constraint(self, db):
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
        with get_connection().cursor() as cursor:
            fix.apply(cursor)

        assert _constraint_exists("examples_car", "unique_make_model")
