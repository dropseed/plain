from __future__ import annotations

from app.examples.models import Car, CarFeature, TreeNode, UnconstrainedChild
from conftest_convergence import (
    constraint_exists,
    constraint_is_deferrable,
    constraint_is_valid,
    execute,
    get_fk_constraint_names,
)

from plain.postgres import get_connection
from plain.postgres.convergence import (
    AddForeignKeyFix,
    DriftKind,
    DropConstraintFix,
    ForeignKeyDrift,
    ValidateConstraintFix,
    analyze_model,
    execute_plan,
    plan_model_convergence,
)
from plain.postgres.convergence.analysis import generate_fk_constraint_name


class TestForeignKeyDetection:
    def test_no_drift_when_fk_exists(self, db):
        """Existing FK constraints from migrations produce no drifts."""
        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, CarFeature)

        fk_drifts = [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)]
        assert fk_drifts == []

    def test_detects_missing_fk(self, db):
        """Dropping an FK constraint produces a MISSING drift."""
        fk_names = get_fk_constraint_names("examples_carfeature")
        assert len(fk_names) >= 1

        # Drop one FK constraint
        execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{fk_names[0]}"')

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, CarFeature)

        missing = [
            d
            for d in analysis.drifts
            if isinstance(d, ForeignKeyDrift) and d.kind == DriftKind.MISSING
        ]
        assert len(missing) == 1
        assert missing[0].table == "examples_carfeature"
        assert missing[0].name is not None

    def test_detects_undeclared_fk(self, db):
        """A manual FK constraint not in the model is UNDECLARED."""
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_fake_fk"'
            ' FOREIGN KEY ("id") REFERENCES "examples_feature" ("id")'
            " DEFERRABLE INITIALLY DEFERRED"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, Car)

        undeclared = [
            d
            for d in analysis.drifts
            if isinstance(d, ForeignKeyDrift) and d.kind == DriftKind.UNDECLARED
        ]
        assert len(undeclared) == 1
        assert undeclared[0].name == "examples_car_fake_fk"

    def test_detects_not_valid_fk(self, db):
        """A NOT VALID FK matching the model shape needs validation."""
        fk_names = get_fk_constraint_names("examples_carfeature")
        assert len(fk_names) >= 1
        fk_name = fk_names[0]

        # Drop and recreate as NOT VALID
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_get_constraintdef(c.oid)
                FROM pg_constraint c
                JOIN pg_class cl ON c.conrelid = cl.oid
                WHERE cl.relname = 'examples_carfeature' AND c.conname = %s
                """,
                [fk_name],
            )
            row = cursor.fetchone()
            assert row is not None
            constraintdef = row[0]

        execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{fk_name}"')
        execute(
            f'ALTER TABLE "examples_carfeature" ADD CONSTRAINT "{fk_name}"'
            f" {constraintdef} NOT VALID"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, CarFeature)

        unvalidated = [
            d
            for d in analysis.drifts
            if isinstance(d, ForeignKeyDrift) and d.kind == DriftKind.UNVALIDATED
        ]
        assert len(unvalidated) == 1
        assert unvalidated[0].name == fk_name

    def test_fk_constraint_name_matches_schema_editor(self, db):
        """generate_fk_constraint_name produces names matching existing migration FKs."""
        fk_names = get_fk_constraint_names("examples_carfeature")

        # CarFeature has car_id → examples_car.id and feature_id → examples_feature.id
        expected_car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )
        expected_feature_fk = generate_fk_constraint_name(
            "examples_carfeature", "feature_id", "examples_feature", "id"
        )

        assert expected_car_fk in fk_names
        assert expected_feature_fk in fk_names


class TestForeignKeyFixes:
    def test_add_fk_creates_and_validates(self, isolated_db):
        """AddForeignKeyFix creates NOT VALID then validates in one apply()."""
        fk_names = get_fk_constraint_names("examples_carfeature")
        car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )

        # Drop the existing FK so we can recreate it
        if car_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{car_fk}"')

        assert not constraint_exists("examples_carfeature", car_fk)

        fix = AddForeignKeyFix(
            table="examples_carfeature",
            constraint_name=car_fk,
            column="car_id",
            target_table="examples_car",
            target_column="id",
        )
        sql = fix.apply()

        assert "NOT VALID" in sql
        assert "VALIDATE CONSTRAINT" in sql
        assert "DEFERRABLE INITIALLY DEFERRED" in sql
        assert constraint_exists("examples_carfeature", car_fk)
        assert constraint_is_valid("examples_carfeature", car_fk)

    def test_validate_fk_after_add(self, isolated_db):
        """ValidateConstraintFix validates a NOT VALID FK."""
        car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )

        # Drop and recreate as NOT VALID
        fk_names = get_fk_constraint_names("examples_carfeature")
        if car_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{car_fk}"')

        execute(
            f'ALTER TABLE "examples_carfeature" ADD CONSTRAINT "{car_fk}"'
            f' FOREIGN KEY ("car_id") REFERENCES "examples_car" ("id")'
            f" DEFERRABLE INITIALLY DEFERRED NOT VALID"
        )
        assert not constraint_is_valid("examples_carfeature", car_fk)

        fix = ValidateConstraintFix(table="examples_carfeature", name=car_fk)
        fix.apply()

        assert constraint_is_valid("examples_carfeature", car_fk)

    def test_fk_is_deferrable(self, isolated_db):
        """Convergence-created FK constraints are DEFERRABLE INITIALLY DEFERRED."""
        car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )

        # Drop and recreate via convergence fix
        fk_names = get_fk_constraint_names("examples_carfeature")
        if car_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{car_fk}"')

        fix = AddForeignKeyFix(
            table="examples_carfeature",
            constraint_name=car_fk,
            column="car_id",
            target_table="examples_car",
            target_column="id",
        )
        fix.apply()

        assert constraint_is_deferrable("examples_carfeature", car_fk)

    def test_undeclared_fk_drop(self, isolated_db):
        """DropConstraintFix drops an undeclared FK."""
        execute(
            'ALTER TABLE "examples_car" ADD CONSTRAINT "examples_car_fake_fk"'
            ' FOREIGN KEY ("id") REFERENCES "examples_feature" ("id")'
            " DEFERRABLE INITIALLY DEFERRED"
        )
        assert constraint_exists("examples_car", "examples_car_fake_fk")

        fix = DropConstraintFix(table="examples_car", name="examples_car_fake_fk")
        fix.apply()

        assert not constraint_exists("examples_car", "examples_car_fake_fk")

    def test_fk_lifecycle(self, isolated_db):
        """Full cycle: drop FK → detect missing → add + validate → converged."""
        car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )

        # Drop existing FK
        fk_names = get_fk_constraint_names("examples_carfeature")
        if car_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{car_fk}"')

        conn = get_connection()

        # Detect missing FK and apply fix (creates + validates in one step)
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, CarFeature).executable()

        add_fk_items = [
            item for item in items if isinstance(item.fix, AddForeignKeyFix)
        ]
        assert len(add_fk_items) == 1
        fix = add_fk_items[0].fix
        assert isinstance(fix, AddForeignKeyFix)
        assert fix.constraint_name == car_fk

        result = execute_plan(items)
        assert result.ok

        # FK is created and fully valid after one pass
        assert constraint_exists("examples_carfeature", car_fk)
        assert constraint_is_valid("examples_carfeature", car_fk)

        # Fully converged — no more work
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, CarFeature).executable()
        assert items == []

    def test_fk_pass_ordering(self, db):
        """FK add (pass 2) comes before FK validate (pass 3)."""
        car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )
        fk_names = get_fk_constraint_names("examples_carfeature")

        # Drop one FK and leave another as NOT VALID to get both in one plan
        feature_fk = generate_fk_constraint_name(
            "examples_carfeature", "feature_id", "examples_feature", "id"
        )

        if car_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{car_fk}"')

        if feature_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{feature_fk}"')
            execute(
                f'ALTER TABLE "examples_carfeature" ADD CONSTRAINT "{feature_fk}"'
                f' FOREIGN KEY ("feature_id") REFERENCES "examples_feature" ("id")'
                f" DEFERRABLE INITIALLY DEFERRED NOT VALID"
            )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, CarFeature).executable()

        fix_types = [type(item.fix) for item in items]
        if AddForeignKeyFix in fix_types and ValidateConstraintFix in fix_types:
            add_idx = max(i for i, t in enumerate(fix_types) if t is AddForeignKeyFix)
            validate_idx = min(
                i for i, t in enumerate(fix_types) if t is ValidateConstraintFix
            )
            assert add_idx < validate_idx

    def test_fk_blocks_sync(self, db):
        """Missing FK blocks sync (correctness convergence)."""
        car_fk = generate_fk_constraint_name(
            "examples_carfeature", "car_id", "examples_car", "id"
        )
        fk_names = get_fk_constraint_names("examples_carfeature")
        if car_fk in fk_names:
            execute(f'ALTER TABLE "examples_carfeature" DROP CONSTRAINT "{car_fk}"')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, CarFeature).executable()

        fk_items = [item for item in items if isinstance(item.fix, AddForeignKeyFix)]
        assert len(fk_items) == 1
        assert fk_items[0].blocks_sync is True


class TestSelfReferentialFK:
    def test_self_referential_fk_converged(self, db):
        """Self-referential FK (TreeNode.parent → TreeNode) is fully converged."""
        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, TreeNode)

        fk_drifts = [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)]
        assert fk_drifts == []

    def test_self_referential_fk_exists(self, db):
        """Self-referential FK constraint exists in the database."""
        fk_names = get_fk_constraint_names("examples_treenode")
        expected = generate_fk_constraint_name(
            "examples_treenode", "parent_id", "examples_treenode", "id"
        )
        assert expected in fk_names

    def test_self_referential_fk_lifecycle(self, isolated_db):
        """Drop and recreate self-referential FK via convergence."""
        expected = generate_fk_constraint_name(
            "examples_treenode", "parent_id", "examples_treenode", "id"
        )
        fk_names = get_fk_constraint_names("examples_treenode")
        if expected in fk_names:
            execute(f'ALTER TABLE "examples_treenode" DROP CONSTRAINT "{expected}"')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, TreeNode).executable()

        add_items = [item for item in items if isinstance(item.fix, AddForeignKeyFix)]
        assert len(add_items) == 1
        fix = add_items[0].fix
        assert isinstance(fix, AddForeignKeyFix)
        assert fix.table == "examples_treenode"
        assert fix.target_table == "examples_treenode"

        result = execute_plan(items)
        assert result.ok
        assert constraint_exists("examples_treenode", expected)
        assert constraint_is_valid("examples_treenode", expected)


class TestDbConstraintFalse:
    def test_no_fk_constraint_for_unconstrained(self, db):
        """db_constraint=False produces no FK constraint and no drift."""
        fk_names = get_fk_constraint_names("examples_unconstrainedchild")
        assert fk_names == []

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, UnconstrainedChild)

        fk_drifts = [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)]
        assert fk_drifts == []
