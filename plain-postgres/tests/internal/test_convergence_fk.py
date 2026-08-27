from __future__ import annotations

from app.examples.models.delete import ChildCascade, ChildSetNull
from app.examples.models.relationships import Widget, WidgetTag
from app.examples.models.trees import TreeNode
from conftest_convergence import (
    constraint_exists,
    constraint_is_valid,
    execute,
    fk_on_delete_action,
    get_fk_constraint_names,
)
from plain.postgres import get_connection
from plain.postgres.convergence import (
    analyze_model,
    execute_plan,
    plan_model_convergence,
)
from plain.postgres.convergence.analysis import (
    DriftKind,
    ForeignKeyChangedDrift,
    ForeignKeyDrift,
    ForeignKeyMissingDrift,
    ForeignKeyNameDrift,
    ForeignKeyRenameDrift,
)
from plain.postgres.convergence.corrections import (
    AddForeignKeyCorrection,
    DropConstraintCorrection,
    RenameConstraintCorrection,
    ReplaceForeignKeyCorrection,
    ValidateConstraintCorrection,
)
from plain.postgres.utils import generate_fk_constraint_name


def _recreate_fk(
    table: str, column: str, target_table: str, target_column: str, *, clause: str
) -> str:
    """Drop the model's FK (if present) and recreate it by hand with
    ``clause`` appended — the way a manual or legacy DDL would have."""
    fk_name = generate_fk_constraint_name(table, column, target_table, target_column)
    execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{fk_name}"')
    execute(
        f'ALTER TABLE "{table}" ADD CONSTRAINT "{fk_name}"'
        f' FOREIGN KEY ("{column}") REFERENCES "{target_table}" ("{target_column}")'
        f"{clause}"
    )
    return fk_name


class TestForeignKeyDetection:
    def test_no_drift_when_fk_exists(self, db):
        """Existing FK constraints from migrations produce no drifts."""
        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, WidgetTag)

        fk_drifts = [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)]
        assert fk_drifts == []

    def test_detects_missing_fk(self, db):
        """Dropping an FK constraint produces a MISSING drift."""
        fk_names = get_fk_constraint_names("examples_widgettag")
        assert len(fk_names) >= 1

        # Drop one FK constraint
        execute(f'ALTER TABLE "examples_widgettag" DROP CONSTRAINT "{fk_names[0]}"')

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, WidgetTag)

        missing = [d for d in analysis.drifts if isinstance(d, ForeignKeyMissingDrift)]
        assert len(missing) == 1
        assert missing[0].table == "examples_widgettag"
        assert missing[0].name is not None

    def test_detects_undeclared_fk(self, db):
        """A manual FK constraint not in the model is UNDECLARED."""
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_fake_fk"'
            ' FOREIGN KEY ("id") REFERENCES "examples_tag" ("id")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, Widget)

        undeclared = [
            d
            for d in analysis.drifts
            if isinstance(d, ForeignKeyNameDrift) and d.kind == DriftKind.UNDECLARED
        ]
        assert len(undeclared) == 1
        assert undeclared[0].name == "examples_widget_fake_fk"

    def test_detects_not_valid_fk(self, db):
        """A NOT VALID FK matching the model shape needs validation."""
        fk_names = get_fk_constraint_names("examples_widgettag")
        assert len(fk_names) >= 1
        fk_name = fk_names[0]

        # Drop and recreate as NOT VALID
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_get_constraintdef(c.oid)
                FROM pg_constraint c
                JOIN pg_class cl ON c.conrelid = cl.oid
                WHERE cl.relname = 'examples_widgettag' AND c.conname = %s
                """,
                [fk_name],
            )
            row = cursor.fetchone()
            assert row is not None
            constraintdef = row[0]

        execute(f'ALTER TABLE "examples_widgettag" DROP CONSTRAINT "{fk_name}"')
        execute(
            f'ALTER TABLE "examples_widgettag" ADD CONSTRAINT "{fk_name}"'
            f" {constraintdef} NOT VALID"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, WidgetTag)

        unvalidated = [
            d
            for d in analysis.drifts
            if isinstance(d, ForeignKeyNameDrift) and d.kind == DriftKind.UNVALIDATED
        ]
        assert len(unvalidated) == 1
        assert unvalidated[0].name == fk_name

    def test_fk_constraint_name_matches_schema_editor(self, db):
        """generate_fk_constraint_name produces names matching existing migration FKs."""
        fk_names = get_fk_constraint_names("examples_widgettag")

        # WidgetTag has widget_id → examples_widget.id and tag_id → examples_tag.id
        expected_widget_fk = generate_fk_constraint_name(
            "examples_widgettag", "widget_id", "examples_widget", "id"
        )
        expected_tag_fk = generate_fk_constraint_name(
            "examples_widgettag", "tag_id", "examples_tag", "id"
        )

        assert expected_widget_fk in fk_names
        assert expected_tag_fk in fk_names


class TestForeignKeyFixes:
    def test_add_fk_creates_and_validates(self, isolated_db):
        """AddForeignKeyCorrection creates NOT VALID then validates in one apply()."""
        fk_names = get_fk_constraint_names("examples_widgettag")
        widget_fk = generate_fk_constraint_name(
            "examples_widgettag", "widget_id", "examples_widget", "id"
        )

        # Drop the existing FK so we can recreate it
        if widget_fk in fk_names:
            execute(f'ALTER TABLE "examples_widgettag" DROP CONSTRAINT "{widget_fk}"')

        assert not constraint_exists("examples_widgettag", widget_fk)

        correction = AddForeignKeyCorrection(
            table="examples_widgettag",
            constraint_name=widget_fk,
            column="widget_id",
            target_table="examples_widget",
            target_column="id",
            on_delete_clause=" ON DELETE CASCADE",
        )
        sql = correction.apply()

        assert "NOT VALID" in sql
        assert "VALIDATE CONSTRAINT" in sql
        assert constraint_exists("examples_widgettag", widget_fk)
        assert constraint_is_valid("examples_widgettag", widget_fk)

    def test_validate_fk_after_add(self, isolated_db):
        """ValidateConstraintCorrection validates a NOT VALID FK."""
        widget_fk = _recreate_fk(
            "examples_widgettag",
            "widget_id",
            "examples_widget",
            "id",
            clause=" ON DELETE CASCADE NOT VALID",
        )
        assert not constraint_is_valid("examples_widgettag", widget_fk)

        correction = ValidateConstraintCorrection(
            table="examples_widgettag", name=widget_fk
        )
        correction.apply()

        assert constraint_is_valid("examples_widgettag", widget_fk)

    def test_undeclared_fk_drop(self, isolated_db):
        """DropConstraintCorrection drops an undeclared FK."""
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_fake_fk"'
            ' FOREIGN KEY ("id") REFERENCES "examples_tag" ("id")'
        )
        assert constraint_exists("examples_widget", "examples_widget_fake_fk")

        correction = DropConstraintCorrection(
            table="examples_widget", name="examples_widget_fake_fk"
        )
        correction.apply()

        assert not constraint_exists("examples_widget", "examples_widget_fake_fk")

    def test_fk_lifecycle(self, isolated_db):
        """Full cycle: drop FK → detect missing → add + validate → converged."""
        widget_fk = generate_fk_constraint_name(
            "examples_widgettag", "widget_id", "examples_widget", "id"
        )

        # Drop existing FK
        fk_names = get_fk_constraint_names("examples_widgettag")
        if widget_fk in fk_names:
            execute(f'ALTER TABLE "examples_widgettag" DROP CONSTRAINT "{widget_fk}"')

        conn = get_connection()

        # Detect missing FK and apply correction (creates + validates in one step)
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, WidgetTag).executable()

        add_fk_items = [
            item
            for item in items
            if isinstance(item.correction, AddForeignKeyCorrection)
        ]
        assert len(add_fk_items) == 1
        correction = add_fk_items[0].correction
        assert isinstance(correction, AddForeignKeyCorrection)
        assert correction.constraint_name == widget_fk

        result = execute_plan(items)
        assert result.ok

        # FK is created and fully valid after one pass
        assert constraint_exists("examples_widgettag", widget_fk)
        assert constraint_is_valid("examples_widgettag", widget_fk)

        # Fully converged — no more work
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, WidgetTag).executable()
        assert items == []

    def test_fk_pass_ordering(self, db):
        """FK add (pass 2) comes before FK validate (pass 3)."""
        widget_fk = generate_fk_constraint_name(
            "examples_widgettag", "widget_id", "examples_widget", "id"
        )
        fk_names = get_fk_constraint_names("examples_widgettag")

        # Drop one FK and leave another as NOT VALID to get both in one plan
        if widget_fk in fk_names:
            execute(f'ALTER TABLE "examples_widgettag" DROP CONSTRAINT "{widget_fk}"')

        _recreate_fk(
            "examples_widgettag",
            "tag_id",
            "examples_tag",
            "id",
            clause=" ON DELETE CASCADE NOT VALID",
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, WidgetTag).executable()

        correction_types = [type(item.correction) for item in items]
        if (
            AddForeignKeyCorrection in correction_types
            and ValidateConstraintCorrection in correction_types
        ):
            add_idx = max(
                i
                for i, t in enumerate(correction_types)
                if t is AddForeignKeyCorrection
            )
            validate_idx = min(
                i
                for i, t in enumerate(correction_types)
                if t is ValidateConstraintCorrection
            )
            assert add_idx < validate_idx

    def test_fk_blocks_sync(self, db):
        """Missing FK blocks sync (correctness convergence)."""
        widget_fk = generate_fk_constraint_name(
            "examples_widgettag", "widget_id", "examples_widget", "id"
        )
        fk_names = get_fk_constraint_names("examples_widgettag")
        if widget_fk in fk_names:
            execute(f'ALTER TABLE "examples_widgettag" DROP CONSTRAINT "{widget_fk}"')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, WidgetTag).executable()

        fk_items = [
            item
            for item in items
            if isinstance(item.correction, AddForeignKeyCorrection)
        ]
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

        add_items = [
            item
            for item in items
            if isinstance(item.correction, AddForeignKeyCorrection)
        ]
        assert len(add_items) == 1
        correction = add_items[0].correction
        assert isinstance(correction, AddForeignKeyCorrection)
        assert correction.table == "examples_treenode"
        assert correction.target_table == "examples_treenode"

        result = execute_plan(items)
        assert result.ok
        assert constraint_exists("examples_treenode", expected)
        assert constraint_is_valid("examples_treenode", expected)


class TestForeignKeyOnDelete:
    """Convergence must treat `on_delete` as part of the FK shape and
    recreate the constraint when the model's action diverges from the DB."""

    def test_fk_emits_on_delete_cascade(self, isolated_db):
        """AddForeignKeyCorrection with ON DELETE CASCADE lands as confdeltype='c'."""
        fk_name = generate_fk_constraint_name(
            "examples_childcascade", "parent_id", "examples_deleteparent", "id"
        )
        fk_names = get_fk_constraint_names("examples_childcascade")
        if fk_name in fk_names:
            execute(f'ALTER TABLE "examples_childcascade" DROP CONSTRAINT "{fk_name}"')

        correction = AddForeignKeyCorrection(
            table="examples_childcascade",
            constraint_name=fk_name,
            column="parent_id",
            target_table="examples_deleteparent",
            target_column="id",
            on_delete_clause=" ON DELETE CASCADE",
        )
        sql = correction.apply()

        assert "ON DELETE CASCADE" in sql
        assert fk_on_delete_action("examples_childcascade", fk_name) == "c"

    def test_detects_on_delete_drift(self, isolated_db):
        """A FK whose DB action differs from the model declaration is CHANGED drift."""
        fk_name = _recreate_fk(
            "examples_childcascade",
            "parent_id",
            "examples_deleteparent",
            "id",
            clause=" ON DELETE NO ACTION",
        )
        assert fk_on_delete_action("examples_childcascade", fk_name) == "a"

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ChildCascade)

        changed = [d for d in analysis.drifts if isinstance(d, ForeignKeyChangedDrift)]
        assert len(changed) == 1
        assert changed[0].actual_action == "a"
        assert changed[0].expected_action == "c"
        assert changed[0].on_delete_clause == " ON DELETE CASCADE"

    def test_replace_fk_updates_action(self, isolated_db):
        """ReplaceForeignKeyCorrection drops + re-adds in one statement, updating confdeltype."""
        fk_name = _recreate_fk(
            "examples_childcascade",
            "parent_id",
            "examples_deleteparent",
            "id",
            clause=" ON DELETE NO ACTION",
        )
        assert fk_on_delete_action("examples_childcascade", fk_name) == "a"

        correction = ReplaceForeignKeyCorrection(
            table="examples_childcascade",
            constraint_name=fk_name,
            column="parent_id",
            target_table="examples_deleteparent",
            target_column="id",
            on_delete_clause=" ON DELETE CASCADE",
        )
        correction.apply()

        assert constraint_exists("examples_childcascade", fk_name)
        assert constraint_is_valid("examples_childcascade", fk_name)
        assert fk_on_delete_action("examples_childcascade", fk_name) == "c"

    def test_on_delete_drift_planned_and_executed(self, isolated_db):
        """End-to-end: DB action 'a' + model CASCADE → CHANGED drift → ReplaceForeignKeyCorrection → 'c'."""
        fk_name = _recreate_fk(
            "examples_childcascade",
            "parent_id",
            "examples_deleteparent",
            "id",
            clause=" ON DELETE NO ACTION",
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ChildCascade).executable()

        replace_items = [
            item
            for item in items
            if isinstance(item.correction, ReplaceForeignKeyCorrection)
        ]
        assert len(replace_items) == 1

        assert execute_plan(items).ok
        assert fk_on_delete_action("examples_childcascade", fk_name) == "c"

    def test_set_null_emits_set_null_clause(self, isolated_db):
        """ChildSetNull has on_delete=SET_NULL — confdeltype should be 'n'."""
        fk_name = generate_fk_constraint_name(
            "examples_childsetnull", "parent_id", "examples_deleteparent", "id"
        )
        # Whatever exists in the test DB should already reflect the model, but
        # after convergence this must be 'n' regardless.
        fk_names = get_fk_constraint_names("examples_childsetnull")
        if fk_name in fk_names:
            execute(f'ALTER TABLE "examples_childsetnull" DROP CONSTRAINT "{fk_name}"')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ChildSetNull).executable()
        assert execute_plan(items).ok

        assert fk_on_delete_action("examples_childsetnull", fk_name) == "n"


class TestForeignKeyRename:
    """RenameField/RenameModel leave the FK constraint under its old name.
    The write path maps a violation back to the field by the generated name,
    so a stale name is drift, fixed with a rename."""

    def test_stale_fk_name_is_rename_drift(self, db):
        expected = generate_fk_constraint_name(
            "examples_childcascade", "parent_id", "examples_deleteparent", "id"
        )
        execute(
            f'ALTER TABLE "examples_childcascade" RENAME CONSTRAINT "{expected}"'
            ' TO "childcascade_old_name_fkey"'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ChildCascade)
        assert [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)] == [
            ForeignKeyRenameDrift(
                table="examples_childcascade",
                old_name="childcascade_old_name_fkey",
                new_name=expected,
            )
        ]
        # One row for the constraint, not a rename row plus a clean row.
        assert [c.name for c in analysis.constraints if c.name == expected] == [
            expected
        ]

    def test_rename_and_on_delete_change_converge_in_one_pass(self, isolated_db):
        """A rename that lands together with an on_delete change: the rename
        is planned first and the replace addresses the new name."""
        expected = generate_fk_constraint_name(
            "examples_childcascade", "parent_id", "examples_deleteparent", "id"
        )
        _recreate_fk(
            "examples_childcascade",
            "parent_id",
            "examples_deleteparent",
            "id",
            clause=" ON DELETE RESTRICT",
        )
        execute(
            f'ALTER TABLE "examples_childcascade" RENAME CONSTRAINT "{expected}"'
            ' TO "childcascade_old_name_fkey"'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, ChildCascade)
        items = plan.executable()
        assert [type(item.correction) for item in items] == [
            RenameConstraintCorrection,
            ReplaceForeignKeyCorrection,
        ]
        assert all(item.blocks_sync for item in items)
        assert execute_plan(items).ok

        assert constraint_exists("examples_childcascade", expected)
        assert fk_on_delete_action("examples_childcascade", expected) == "c"
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ChildCascade)
        assert [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)] == []

    def test_stale_fk_name_is_renamed(self, isolated_db):
        expected = generate_fk_constraint_name(
            "examples_childcascade", "parent_id", "examples_deleteparent", "id"
        )
        execute(
            f'ALTER TABLE "examples_childcascade" RENAME CONSTRAINT "{expected}"'
            ' TO "childcascade_old_name_fkey"'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ChildCascade).executable()
        assert [type(item.correction) for item in items] == [RenameConstraintCorrection]
        assert execute_plan(items).ok
        assert constraint_exists("examples_childcascade", expected)

        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ChildCascade)
        assert [d for d in analysis.drifts if isinstance(d, ForeignKeyDrift)] == []
