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
    IndexDrift,
    RenameConstraintFix,
    ValidateConstraintFix,
    analyze_model,
    can_auto_fix,
    plan_convergence,
    plan_model_convergence,
)
from plain.postgres.functions.text import Upper


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

    def test_detects_unique_constraint_definition_changed(self, db):
        """A unique constraint with matching name but different columns is blocked."""
        # DB already has unique_make_model on ("make", "model")
        # Model declares unique on ("make") only — same name, different columns
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            UniqueConstraint(fields=["make"], name="unique_make_model"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None
            assert plan.blocked[0].guidance is not None
        finally:
            Car.model_options.constraints = original_constraints

    def test_no_false_positive_for_matching_unique_constraint(self, db):
        """A unique constraint with matching name and matching columns has no issues."""
        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, Car)

        # The existing unique_make_model on ("make", "model") matches the model
        assert plan.executable() == []
        assert plan.blocked == []

    def test_detects_unique_deferrable_changed(self, db):
        """Same columns but different deferrable setting is a definition change."""
        # DB has non-deferrable unique_make_model; model declares it deferrable
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            UniqueConstraint(
                fields=["make", "model"],
                name="unique_make_model",
                deferrable=Deferrable.DEFERRED,
            ),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
        finally:
            Car.model_options.constraints = original_constraints

    def test_detects_unique_include_changed(self, isolated_db):
        """Same columns but added INCLUDE column is a definition change."""
        # Drop the existing constraint and recreate with INCLUDE
        execute('ALTER TABLE "examples_car" DROP CONSTRAINT "unique_make_model"')
        execute(
            'CREATE UNIQUE INDEX "unique_make_model" ON "examples_car" ("make", "model")'
        )
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "unique_make_model"'
            ' UNIQUE USING INDEX "unique_make_model"'
        )

        # Model now expects INCLUDE ("id") — DB has no INCLUDE
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            UniqueConstraint(
                fields=["make", "model"],
                name="unique_make_model",
                include=["id"],
            ),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
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

    def test_check_definition_change_is_blocked(self, isolated_db):
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

    def test_unique_definition_change_is_blocked(self, isolated_db):
        """Changed unique columns is blocked — no auto-fix available."""
        # DB has unique_make_model on ("make", "model")
        # Model declares unique on ("make") only — same name, different columns
        original_constraints = list(Car.model_options.constraints)
        Car.model_options.constraints = [
            UniqueConstraint(fields=["make"], name="unique_make_model"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None

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


class TestIndexBackedUniqueConstraints:
    """Tests for UniqueConstraint variants that PostgreSQL can only store as
    indexes (condition, expressions, opclasses).  These must go through the
    index creation path, not the constraint attachment path."""

    # -- Gap 1: AddConstraintFix should not try USING INDEX for these --

    def test_add_conditional_unique_succeeds(self, isolated_db):
        """A conditional unique constraint should be created as an index, not fail."""
        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["make"],
            condition=Q(model__isnull=False),
            name="examples_car_make_conditional_uq",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            # Should produce a fix
            assert len(items) >= 1
            fix = next(
                i.fix for i in items if getattr(i.fix, "constraint", None) is constraint
            )
            assert fix is not None
            sql = fix.apply()
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_car_make_conditional_uq")
        finally:
            Car.model_options.constraints = original_constraints

    def test_add_expression_unique_succeeds(self, isolated_db):
        """An expression-based unique constraint should be created as an index."""
        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            Upper("make"),
            name="examples_car_make_upper_uq",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert len(items) >= 1
            fix = next(
                i.fix for i in items if getattr(i.fix, "constraint", None) is constraint
            )
            assert fix is not None
            sql = fix.apply()
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_car_make_upper_uq")
        finally:
            Car.model_options.constraints = original_constraints

    # -- Gap 2: matching index-backed unique should not produce false drift --

    def test_matching_conditional_unique_no_drift(self, db):
        """An existing partial unique index matching the model has no issues."""
        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["make"],
            condition=Q(model__isnull=False),
            name="examples_car_make_partial_uq",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        # Create the index using the model's own to_sql so the definition matches
        execute(constraint.to_sql(Car))

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            # Should be fully converged — no missing, no changed
            constraint_drifts = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift)
                and d.drift.constraint is not None
                and d.drift.constraint.name == "examples_car_make_partial_uq"
            ]
            assert constraint_drifts == [], (
                f"Expected no drift for matching partial unique, got: "
                f"{[d.describe() for d in constraint_drifts]}"
            )
        finally:
            Car.model_options.constraints = original_constraints

    def test_matching_expression_unique_no_drift(self, db):
        """An existing expression unique index matching the model has no issues."""
        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            Upper("make"),
            name="examples_car_make_upper_uq",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        execute(
            'CREATE UNIQUE INDEX "examples_car_make_upper_uq"'
            ' ON "examples_car" (UPPER("make"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            constraint_drifts = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift)
                and d.drift.constraint is not None
                and d.drift.constraint.name == "examples_car_make_upper_uq"
            ]
            assert constraint_drifts == [], (
                f"Expected no drift for matching expression unique, got: "
                f"{[d.describe() for d in constraint_drifts]}"
            )
        finally:
            Car.model_options.constraints = original_constraints

    # -- Gap 3: full lifecycle converges (create → re-check → no work) --

    def test_conditional_unique_lifecycle(self, isolated_db):
        """Create conditional unique → re-check → converged (no perpetual failure)."""
        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["make"],
            condition=Q(model__isnull=False),
            name="examples_car_make_partial_uq",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        try:
            conn = get_connection()

            # First pass: creates the index
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert any(getattr(i.fix, "constraint", None) is constraint for i in items)
            for item in items:
                if getattr(item.fix, "constraint", None) is constraint:
                    assert item.fix is not None
                    item.fix.apply()

            # Second pass: should be fully converged
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            remaining = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift | IndexDrift)
                and getattr(d.drift, "name", None) == "examples_car_make_partial_uq"
            ]
            assert remaining == [], (
                f"Expected convergence after creation, got: "
                f"{[d.drift.describe() for d in remaining]}"
            )
        finally:
            Car.model_options.constraints = original_constraints

    # -- Gap 4: condition/opclass changes detected as CHANGED --

    def test_detects_condition_change_on_partial_unique(self, db):
        """Same name and columns but different WHERE clause is a definition change."""
        original_constraints = list(Car.model_options.constraints)
        # Model declares WHERE (model IS NOT NULL)
        constraint = UniqueConstraint(
            fields=["make"],
            condition=Q(model__isnull=False),
            name="examples_car_make_partial_uq",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        # DB has a different condition: WHERE (id > 100)
        execute(
            'CREATE UNIQUE INDEX "examples_car_make_partial_uq"'
            ' ON "examples_car" ("make")'
            ' WHERE ("id" > 100)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
        finally:
            Car.model_options.constraints = original_constraints

    # -- Gap 5: rename/drop use correct fix types for index-only --

    def test_undeclared_index_only_unique_uses_drop_index(self, db):
        """Undeclared index-only unique should use DropIndexFix, not DropConstraintFix."""
        from plain.postgres.convergence import DropIndexFix

        execute(
            'CREATE UNIQUE INDEX "examples_car_old_partial_uq"'
            ' ON "examples_car" ("make")'
            ' WHERE ("id" > 0)'
        )

        plan = plan_convergence()
        undeclared = [
            item
            for item in plan.items
            if isinstance(item.drift, IndexDrift)
            and item.drift.kind == DriftKind.UNDECLARED
            and item.drift.name == "examples_car_old_partial_uq"
        ]
        assert len(undeclared) == 1
        assert isinstance(undeclared[0].fix, DropIndexFix)

    def test_rename_index_only_unique_uses_rename_index(self, db):
        """Renaming an index-only unique should use RenameIndexFix."""
        from plain.postgres.convergence import RenameIndexFix

        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["make"],
            condition=Q(model__isnull=False),
            name="examples_car_make_partial_new",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        # Create the matching index under the old name
        execute(constraint.to_sql(Car).replace("_new", "_old"))

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Car)

            rename_items = [
                item
                for item in plan.items
                if isinstance(item.drift, IndexDrift)
                and item.drift.kind == DriftKind.RENAMED
            ]
            assert len(rename_items) == 1
            assert isinstance(rename_items[0].fix, RenameIndexFix)
        finally:
            Car.model_options.constraints = original_constraints

    def test_no_rename_when_condition_differs(self, db):
        """Same columns + different condition + different name is NOT a rename."""
        original_constraints = list(Car.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["make"],
            condition=Q(id__gt=0),
            name="examples_car_make_partial_new",
        )
        Car.model_options.constraints = [*original_constraints, constraint]

        # DB has the same columns but a different condition
        execute(
            'CREATE UNIQUE INDEX "examples_car_make_partial_old"'
            ' ON "examples_car" ("make")'
            ' WHERE ("id" > 100)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Car)

            # Should NOT be classified as a rename — semantics differ
            assert not any(
                isinstance(d, ConstraintDrift | IndexDrift)
                and d.kind == DriftKind.RENAMED
                for d in analysis.drifts
            )
            # Should see separate missing + undeclared instead
            assert any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
        finally:
            Car.model_options.constraints = original_constraints
