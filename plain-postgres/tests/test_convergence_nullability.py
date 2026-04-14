from __future__ import annotations

from app.examples.models.delete import ChildSetNull
from app.examples.models.nullability import NullabilityExample
from app.examples.models.trees import TreeNode
from conftest_convergence import column_is_not_null, constraint_exists, execute

from plain.postgres import get_connection
from plain.postgres.convergence import (
    DropNotNullFix,
    NullabilityDrift,
    SetNotNullFix,
    analyze_model,
    can_auto_fix,
    plan_model_convergence,
)


class TestNotNullDetection:
    def test_detects_nullable_drift(self, db):
        """Non-nullable model field + nullable DB column creates NullabilityDrift."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, NullabilityExample)

        null_drifts = [d for d in analysis.drifts if isinstance(d, NullabilityDrift)]
        assert len(null_drifts) == 1
        assert null_drifts[0].table == "examples_nullabilityexample"
        assert null_drifts[0].column == "required_text"
        assert not null_drifts[0].has_null_rows

    def test_no_drift_when_converged(self, db):
        """Non-nullable model field + NOT NULL DB column creates no drift."""
        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, NullabilityExample)

        null_drifts = [d for d in analysis.drifts if isinstance(d, NullabilityDrift)]
        assert null_drifts == []

    def test_no_drift_for_nullable_field(self, db):
        """Nullable model field + nullable DB column creates no drift."""
        # TreeNode.parent is allow_null=True, DB column is nullable
        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, TreeNode)

        null_drifts = [d for d in analysis.drifts if isinstance(d, NullabilityDrift)]
        assert null_drifts == []

    def test_has_null_rows_flag(self, db):
        """Drift correctly reports whether NULL rows exist."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )
        execute('INSERT INTO "examples_nullabilityexample" DEFAULT VALUES')

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, NullabilityExample)

        null_drifts = [d for d in analysis.drifts if isinstance(d, NullabilityDrift)]
        assert len(null_drifts) == 1
        assert null_drifts[0].has_null_rows is True

    def test_column_status_carries_drift(self, db):
        """ColumnStatus has the drift object for nullable columns."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, NullabilityExample)

        required_col = [c for c in analysis.columns if c.name == "required_text"]
        assert len(required_col) == 1
        assert required_col[0].drift is not None
        assert isinstance(required_col[0].drift, NullabilityDrift)
        assert required_col[0].issue == "expected NOT NULL, actual NULL"

    def test_issue_text_with_null_rows(self, db):
        """Issue text mentions NULL rows when they exist."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )
        execute('INSERT INTO "examples_nullabilityexample" DEFAULT VALUES')

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, NullabilityExample)

        required_col = [c for c in analysis.columns if c.name == "required_text"]
        assert len(required_col) == 1
        assert (
            required_col[0].issue == "expected NOT NULL, actual NULL (NULL rows exist)"
        )

    def test_issue_count_includes_nullability(self, db):
        """Nullability issues are counted in issue_count."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, NullabilityExample)

        assert analysis.issue_count >= 1


class TestNotNullPlanning:
    def test_executable_when_no_null_rows(self, db):
        """No NULL rows → executable SetNotNullFix."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, NullabilityExample)

        items = plan.executable()
        null_fixes = [i for i in items if isinstance(i.fix, SetNotNullFix)]
        assert len(null_fixes) == 1
        fix = null_fixes[0].fix
        assert isinstance(fix, SetNotNullFix)
        assert fix.table == "examples_nullabilityexample"
        assert fix.column == "required_text"

    def test_blocked_when_null_rows_exist(self, db):
        """NULL rows → blocked plan item with guidance."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )
        execute('INSERT INTO "examples_nullabilityexample" DEFAULT VALUES')

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, NullabilityExample)

        null_fixes = [i for i in plan.executable() if isinstance(i.fix, SetNotNullFix)]
        assert null_fixes == []

        blocked = [i for i in plan.blocked if isinstance(i.drift, NullabilityDrift)]
        assert len(blocked) == 1
        assert blocked[0].fix is None
        assert blocked[0].guidance is not None
        assert "NULL" in blocked[0].guidance

    def test_blocks_sync(self, db):
        """SetNotNullFix blocks sync (correctness convergence)."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(
                conn, cursor, NullabilityExample
            ).executable()

        null_fixes = [i for i in items if isinstance(i.fix, SetNotNullFix)]
        assert len(null_fixes) == 1
        assert null_fixes[0].blocks_sync is True

    def test_can_auto_fix_no_nulls(self):
        """can_auto_fix returns True for NullabilityDrift with no null rows."""
        drift = NullabilityDrift(
            table="t", column="c", model_allows_null=False, has_null_rows=False
        )
        assert can_auto_fix(drift)

    def test_can_auto_fix_with_nulls(self):
        """can_auto_fix returns False for NullabilityDrift with null rows."""
        drift = NullabilityDrift(
            table="t", column="c", model_allows_null=False, has_null_rows=True
        )
        assert not can_auto_fix(drift)

    def test_can_auto_fix_drop_not_null(self):
        """can_auto_fix returns True for NullabilityDrift (model allows NULL)."""
        drift = NullabilityDrift(table="t", column="c", model_allows_null=True)
        assert can_auto_fix(drift)


class TestNotNullFixes:
    def test_apply_set_not_null(self, isolated_db):
        """SetNotNullFix uses safe CHECK NOT VALID → VALIDATE → SET NOT NULL."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )
        assert not column_is_not_null("examples_nullabilityexample", "required_text")

        fix = SetNotNullFix(table="examples_nullabilityexample", column="required_text")
        sql = fix.apply()

        # Verify the four-step safe pattern
        assert "NOT VALID" in sql
        assert "VALIDATE CONSTRAINT" in sql
        assert "SET NOT NULL" in sql
        assert column_is_not_null("examples_nullabilityexample", "required_text")
        # Temp check constraint is cleaned up
        from plain.postgres.convergence.analysis import generate_notnull_check_name

        assert not constraint_exists(
            "examples_nullabilityexample",
            generate_notnull_check_name("examples_nullabilityexample", "required_text"),
        )

    def test_set_not_null_lifecycle(self, isolated_db):
        """Full cycle: drop NOT NULL → detect → fix → converged."""
        execute(
            'ALTER TABLE "examples_nullabilityexample" ALTER COLUMN "required_text" DROP NOT NULL'
        )

        conn = get_connection()

        # First pass: detect drift, plan fix
        with conn.cursor() as cursor:
            items = plan_model_convergence(
                conn, cursor, NullabilityExample
            ).executable()
        null_fixes = [i for i in items if isinstance(i.fix, SetNotNullFix)]
        assert len(null_fixes) == 1
        fix = null_fixes[0].fix
        assert isinstance(fix, SetNotNullFix)

        fix.apply()
        assert column_is_not_null("examples_nullabilityexample", "required_text")

        # Second pass: converged
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, NullabilityExample)
        null_drifts = [i for i in plan.items if isinstance(i.drift, NullabilityDrift)]
        assert null_drifts == []

    def test_set_not_null_describe(self):
        """SetNotNullFix.describe() is clear."""
        fix = SetNotNullFix(table="examples_nullabilityexample", column="required_text")
        assert (
            fix.describe()
            == "examples_nullabilityexample: set NOT NULL on required_text"
        )

    def test_set_not_null_pass_order(self):
        """SetNotNullFix runs at pass 2 (alongside constraint additions)."""
        assert SetNotNullFix.pass_order == 2


class TestDropNotNull:
    def test_detects_too_strict_column(self, db):
        """Nullable model field + NOT NULL DB column creates NullabilityDrift."""
        # ChildSetNull.parent is allow_null=True; set the column to NOT NULL
        execute(
            'ALTER TABLE "examples_childsetnull" ALTER COLUMN "parent_id" SET NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ChildSetNull)

        null_drifts = [d for d in analysis.drifts if isinstance(d, NullabilityDrift)]
        assert len(null_drifts) == 1
        assert null_drifts[0].model_allows_null is True

    def test_plans_drop_not_null(self, db):
        """Nullable model + NOT NULL DB → executable DropNotNullFix."""
        execute(
            'ALTER TABLE "examples_childsetnull" ALTER COLUMN "parent_id" SET NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, ChildSetNull)

        items = plan.executable()
        drop_fixes = [i for i in items if isinstance(i.fix, DropNotNullFix)]
        assert len(drop_fixes) == 1
        fix = drop_fixes[0].fix
        assert isinstance(fix, DropNotNullFix)
        assert fix.column == "parent_id"
        assert drop_fixes[0].blocks_sync is True

    def test_apply_drop_not_null(self, isolated_db):
        """DropNotNullFix applies DROP NOT NULL on the column."""
        # parent_id starts nullable; force it NOT NULL then fix it
        execute(
            'ALTER TABLE "examples_childsetnull" ALTER COLUMN "parent_id" SET NOT NULL'
        )
        assert column_is_not_null("examples_childsetnull", "parent_id")

        fix = DropNotNullFix(table="examples_childsetnull", column="parent_id")
        sql = fix.apply()

        assert "DROP NOT NULL" in sql
        assert not column_is_not_null("examples_childsetnull", "parent_id")

    def test_drop_not_null_lifecycle(self, isolated_db):
        """Full cycle: set NOT NULL → detect → fix → converged."""
        execute(
            'ALTER TABLE "examples_childsetnull" ALTER COLUMN "parent_id" SET NOT NULL'
        )

        conn = get_connection()

        # First pass: detect drift, plan fix
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ChildSetNull).executable()
        drop_fixes = [i for i in items if isinstance(i.fix, DropNotNullFix)]
        assert len(drop_fixes) == 1
        fix = drop_fixes[0].fix
        assert isinstance(fix, DropNotNullFix)

        fix.apply()
        assert not column_is_not_null("examples_childsetnull", "parent_id")

        # Second pass: converged
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, ChildSetNull)
        null_drifts = [i for i in plan.items if isinstance(i.drift, NullabilityDrift)]
        assert null_drifts == []

    def test_drop_not_null_describe(self):
        """DropNotNullFix.describe() is clear."""
        fix = DropNotNullFix(
            table="examples_nullabilityexample", column="required_text"
        )
        assert (
            fix.describe()
            == "examples_nullabilityexample: drop NOT NULL on required_text"
        )
