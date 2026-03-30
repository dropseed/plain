from __future__ import annotations

import pytest
from app.examples.models import Car
from conftest_convergence import (
    constraint_exists,
    constraint_is_deferrable,
    constraint_is_valid,
    execute,
    index_exists,
)

from plain.postgres import CheckConstraint, Q, UniqueConstraint, get_connection
from plain.postgres.constraints import Deferrable
from plain.postgres.convergence import (
    AddConstraintFix,
    ConstraintDrift,
    DriftKind,
    DropConstraintFix,
    RenameConstraintFix,
    ValidateConstraintFix,
    analyze_model,
    can_auto_fix,
    plan_model_convergence,
)


class TestDetectConstraintFixes:
    def test_no_fixes_when_converged(self, db):
        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()
        assert items == []

    def test_detects_extra_check_constraint_with_prune(self, db):
        execute(
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
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_test_check" CHECK ("id" >= 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()

        assert items == []

    def test_detects_extra_unique_constraint_with_prune(self, db):
        execute(
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
        execute(
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
        execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')

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

        execute(
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
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            # Changed constraint definition has no auto-fix
            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
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
        execute(
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
            assert constraint_exists("examples_car", "examples_car_id_nonneg")
            assert not constraint_is_valid("examples_car", "examples_car_id_nonneg")
        finally:
            Car.model_options.constraints = original_constraints

    def test_validate_constraint(self, isolated_db):
        """ValidateConstraintFix validates a NOT VALID constraint."""
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )
        assert not constraint_is_valid("examples_car", "examples_car_id_nonneg")

        fix = ValidateConstraintFix(table="examples_car", name="examples_car_id_nonneg")
        fix.apply()

        assert constraint_is_valid("examples_car", "examples_car_id_nonneg")

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
            assert not constraint_is_valid("examples_car", "examples_car_id_nonneg")

            # Second converge pass: detects NOT VALID, validates
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, ValidateConstraintFix)

            items[0].fix.apply()
            assert constraint_is_valid("examples_car", "examples_car_id_nonneg")

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
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()

            # Detects definition change as blocked (no executable fix)
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None

            # can_auto_fix returns False for changed constraints
            assert not can_auto_fix(plan.blocked[0].drift)
        finally:
            Car.model_options.constraints = original_constraints

    def test_apply_drop_constraint(self, isolated_db):
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_temp_check" CHECK ("id" >= 0)'
        )
        assert constraint_exists("examples_car", "examples_car_temp_check")

        fix = DropConstraintFix(table="examples_car", name="examples_car_temp_check")
        fix.apply()

        assert not constraint_exists("examples_car", "examples_car_temp_check")

    def test_add_unique_using_index(self, isolated_db):
        """Unique constraints use CONCURRENTLY + USING INDEX."""
        # Drop the constraint AND its backing index
        execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        assert not constraint_exists("examples_car", "unique_make_model")

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
        assert constraint_exists("examples_car", "unique_make_model")

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
            assert constraint_exists("examples_car", constraint.name)
            assert constraint_is_deferrable("examples_car", constraint.name)
        finally:
            Car.model_options.constraints = original_constraints


class TestConstraintRename:
    def test_rename_check_constraint(self, db):
        """A missing + extra check constraint with same expression is a rename."""
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_car_id_new"),
        ]
        execute(
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
        execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        execute(
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
        execute(
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
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "old_check" CHECK ("id" >= 0)'
        )
        assert constraint_exists("examples_car", "old_check")

        fix = RenameConstraintFix(
            table="examples_car",
            old_name="old_check",
            new_name="new_check",
        )
        sql = fix.apply()

        assert "RENAME CONSTRAINT" in sql
        assert not constraint_exists("examples_car", "old_check")
        assert constraint_exists("examples_car", "new_check")

    def test_rename_unique_renames_backing_index(self, isolated_db):
        """Renaming a unique constraint also renames its backing index."""
        execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "old_unique"'
            ' UNIQUE ("make", "model")'
        )
        assert constraint_exists("examples_car", "old_unique")
        assert index_exists("old_unique")

        fix = RenameConstraintFix(
            table="examples_car",
            old_name="old_unique",
            new_name="new_unique",
        )
        fix.apply()

        assert constraint_exists("examples_car", "new_unique")
        assert index_exists("new_unique")
        assert not constraint_exists("examples_car", "old_unique")
        assert not index_exists("old_unique")

    def test_rename_constraint_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_car_id_new"),
        ]
        execute(
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
