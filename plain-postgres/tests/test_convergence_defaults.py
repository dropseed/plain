from __future__ import annotations

from app.examples.models.defaults import DBDefaultsExample, DefaultsExample
from conftest_convergence import column_default_sql, execute

from plain.postgres import get_connection
from plain.postgres.convergence import (
    ColumnDefaultDrift,
    DriftKind,
    NullabilityDrift,
    SetColumnDefaultFix,
    SetNotNullFix,
    analyze_model,
    can_auto_fix,
    execute_plan,
    plan_model_convergence,
)
from plain.postgres.convergence.fixes import DropColumnDefaultFix


class TestColumnDefaultDetection:
    def test_no_drift_when_converged(self, db):
        """Model declares expression default, DB has matching DEFAULT → no drift."""
        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DBDefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert default_drifts == []

    def test_detects_missing_default(self, db):
        """Manual DROP DEFAULT in DB while model declares one → MISSING drift."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is None

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DBDefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].kind == DriftKind.MISSING
        assert default_drifts[0].table == "examples_dbdefaultsexample"
        assert default_drifts[0].column == "db_uuid"
        assert default_drifts[0].db_default_sql is None
        assert default_drifts[0].model_default_sql is not None
        assert "gen_random_uuid()" in default_drifts[0].model_default_sql

    def test_detects_changed_default(self, db):
        """DB has a different DEFAULT than the model declares → CHANGED drift."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" SET DEFAULT clock_timestamp()'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DBDefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].kind == DriftKind.CHANGED
        assert default_drifts[0].column == "created_at"
        assert default_drifts[0].db_default_sql is not None
        assert "clock_timestamp" in default_drifts[0].db_default_sql
        assert default_drifts[0].model_default_sql is not None
        assert "statement_timestamp" in default_drifts[0].model_default_sql.lower()

    def test_column_status_carries_default_drift(self, db):
        """ColumnStatus.drifts contains a ColumnDefaultDrift for the column."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" DROP DEFAULT'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DBDefaultsExample)

        created_col = [c for c in analysis.columns if c.name == "created_at"]
        assert len(created_col) == 1
        default_drifts = [
            d for d in created_col[0].drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].kind == DriftKind.MISSING
        assert created_col[0].issue is not None

    def test_no_drift_when_static_default_stripped(self, db):
        """Static defaults are stripped from the column after ADD COLUMN, so
        both the model's static default and the bare DB column agree (no
        DB-side DEFAULT).  No drift."""
        assert column_default_sql("examples_defaultsexample", "status") is None

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert default_drifts == []

    def test_no_drift_when_callable_default_stripped(self, db):
        """Callable defaults (e.g. uuid.uuid4) are evaluated in Python; Plain
        strips them from the column, so DB has no DEFAULT and there's no drift."""
        assert column_default_sql("examples_defaultsexample", "token_uuid") is None

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert default_drifts == []

    def test_detects_undeclared_default_on_static_field(self, db):
        """Manual SET DEFAULT on a column whose model declares a static (or
        no) default → UNDECLARED drift.  Plain owns column DEFAULTs; if you
        want one to persist, use a `DatabaseDefaultExpression` subclass."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"status\" SET DEFAULT 'manual-default'"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].kind == DriftKind.UNDECLARED
        assert default_drifts[0].column == "status"
        assert default_drifts[0].db_default_sql is not None
        assert "manual-default" in default_drifts[0].db_default_sql
        assert default_drifts[0].model_default_sql is None


class TestColumnDefaultPlanning:
    def test_plans_set_default_for_missing(self, db):
        """MISSING drift → executable SetColumnDefaultFix."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, DBDefaultsExample)

        fixes = [i for i in plan.executable() if isinstance(i.fix, SetColumnDefaultFix)]
        assert len(fixes) == 1
        fix = fixes[0].fix
        assert isinstance(fix, SetColumnDefaultFix)
        assert fix.table == "examples_dbdefaultsexample"
        assert fix.column == "db_uuid"
        assert "gen_random_uuid()" in fix.default_sql

    def test_plans_set_default_for_changed(self, db):
        """CHANGED drift → executable SetColumnDefaultFix that overwrites."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" SET DEFAULT clock_timestamp()'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, DBDefaultsExample)

        fixes = [i for i in plan.executable() if isinstance(i.fix, SetColumnDefaultFix)]
        assert len(fixes) == 1
        fix = fixes[0].fix
        assert isinstance(fix, SetColumnDefaultFix)
        assert fix.column == "created_at"
        assert "statement_timestamp" in fix.default_sql.lower()

    def test_blocks_sync(self, db):
        """SetColumnDefaultFix blocks sync (correctness convergence)."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        fixes = [i for i in items if isinstance(i.fix, SetColumnDefaultFix)]
        assert len(fixes) == 1
        assert fixes[0].blocks_sync is True

    def test_can_auto_fix_missing(self):
        drift = ColumnDefaultDrift(
            kind=DriftKind.MISSING,
            table="t",
            column="c",
            db_default_sql=None,
            model_default_sql="gen_random_uuid()",
        )
        assert can_auto_fix(drift)

    def test_can_auto_fix_changed(self):
        drift = ColumnDefaultDrift(
            kind=DriftKind.CHANGED,
            table="t",
            column="c",
            db_default_sql="now()",
            model_default_sql="gen_random_uuid()",
        )
        assert can_auto_fix(drift)

    def test_plans_drop_default_for_undeclared(self, db):
        """UNDECLARED drift → executable DropColumnDefaultFix."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"status\" SET DEFAULT 'manual-default'"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, DefaultsExample)

        fixes = [
            i for i in plan.executable() if isinstance(i.fix, DropColumnDefaultFix)
        ]
        assert len(fixes) == 1
        fix = fixes[0].fix
        assert isinstance(fix, DropColumnDefaultFix)
        assert fix.column == "status"
        assert fixes[0].blocks_sync is True

    def test_can_auto_fix_undeclared(self):
        drift = ColumnDefaultDrift(
            kind=DriftKind.UNDECLARED,
            table="t",
            column="c",
            db_default_sql="'x'::text",
            model_default_sql=None,
        )
        assert can_auto_fix(drift)


class TestColumnDefaultFixes:
    def test_apply_set_default(self, isolated_db):
        """SetColumnDefaultFix installs the provided SQL as the column DEFAULT."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is None

        fix = SetColumnDefaultFix(
            table="examples_dbdefaultsexample",
            column="db_uuid",
            default_sql="gen_random_uuid()",
        )
        sql = fix.apply()

        assert "SET DEFAULT gen_random_uuid()" in sql
        default = column_default_sql("examples_dbdefaultsexample", "db_uuid")
        assert default is not None
        assert "gen_random_uuid()" in default

    def test_apply_set_default_replaces_existing(self, isolated_db):
        """SetColumnDefaultFix overwrites an existing DEFAULT in one statement."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" SET DEFAULT clock_timestamp()'
        )

        fix = SetColumnDefaultFix(
            table="examples_dbdefaultsexample",
            column="created_at",
            default_sql="statement_timestamp()",
        )
        fix.apply()

        default = column_default_sql("examples_dbdefaultsexample", "created_at")
        assert default is not None
        assert "statement_timestamp" in default.lower()
        assert "clock_timestamp" not in default

    def test_apply_drop_default(self, isolated_db):
        """DropColumnDefaultFix removes the column DEFAULT."""
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is not None

        fix = DropColumnDefaultFix(table="examples_dbdefaultsexample", column="db_uuid")
        sql = fix.apply()

        assert "DROP DEFAULT" in sql
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is None

    def test_set_default_describe(self):
        fix = SetColumnDefaultFix(
            table="examples_dbdefaultsexample",
            column="db_uuid",
            default_sql="gen_random_uuid()",
        )
        assert (
            fix.describe()
            == "examples_dbdefaultsexample: set DEFAULT gen_random_uuid() on db_uuid"
        )

    def test_drop_default_describe(self):
        fix = DropColumnDefaultFix(table="examples_dbdefaultsexample", column="db_uuid")
        assert fix.describe() == "examples_dbdefaultsexample: drop DEFAULT on db_uuid"

    def test_set_default_pass_order(self):
        """SetColumnDefaultFix runs at pass 2 alongside NOT NULL changes."""
        assert SetColumnDefaultFix.pass_order == 2

    def test_drop_default_pass_order(self):
        assert DropColumnDefaultFix.pass_order == 2


class TestColumnDefaultLifecycle:
    def test_drift_correction_end_to_end(self, isolated_db):
        """Manual DROP DEFAULT → detect MISSING → plan → execute → converged."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )

        conn = get_connection()

        # First pass: detect drift, plan fix
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        fixes = [i for i in items if isinstance(i.fix, SetColumnDefaultFix)]
        assert len(fixes) == 1

        result = execute_plan(items)
        assert result.ok

        default = column_default_sql("examples_dbdefaultsexample", "db_uuid")
        assert default is not None
        assert "gen_random_uuid()" in default

        # Second pass: fully converged
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()
        default_fixes = [i for i in items if isinstance(i.fix, SetColumnDefaultFix)]
        assert default_fixes == []

    def test_undeclared_default_end_to_end(self, isolated_db):
        """Removing an expression default from the model (or a manual SET
        DEFAULT on an undeclared column) → detect UNDECLARED → DROP → converged.

        Simulates "user removed `default=Now()` from the model" by setting
        a DEFAULT on a column whose field declares no expression default."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"status\" SET DEFAULT 'manual-default'"
        )
        assert column_default_sql("examples_defaultsexample", "status") is not None

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DefaultsExample).executable()

        drop_items = [i for i in items if isinstance(i.fix, DropColumnDefaultFix)]
        assert len(drop_items) == 1

        result = execute_plan(items)
        assert result.ok
        assert column_default_sql("examples_defaultsexample", "status") is None

        # Second pass: fully converged
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DefaultsExample).executable()
        assert not [i for i in items if isinstance(i.fix, DropColumnDefaultFix)]

    def test_column_carries_both_nullability_and_default_drifts(self, isolated_db):
        """A column with both kinds of drift populates `drifts` with both,
        and convergence applies both fixes in one plan."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP NOT NULL'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DBDefaultsExample)

        db_uuid_col = [c for c in analysis.columns if c.name == "db_uuid"]
        assert len(db_uuid_col) == 1
        drift_types = {type(d) for d in db_uuid_col[0].drifts}
        assert NullabilityDrift in drift_types
        assert ColumnDefaultDrift in drift_types

        # Plan carries both fixes
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        fix_types = {type(item.fix) for item in items}
        assert SetNotNullFix in fix_types
        assert SetColumnDefaultFix in fix_types

        assert execute_plan(items).ok

        # Both fixes applied — column is NOT NULL again and DEFAULT restored
        default = column_default_sql("examples_dbdefaultsexample", "db_uuid")
        assert default is not None
        assert "gen_random_uuid()" in default

    def test_changed_default_end_to_end(self, isolated_db):
        """Wrong DEFAULT → detect CHANGED → plan → execute → converged."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" SET DEFAULT now()'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        fixes = [i for i in items if isinstance(i.fix, SetColumnDefaultFix)]
        # Only `created_at` should need fixing; db_uuid already matches.
        assert any(
            f.fix.column == "created_at"
            for f in fixes
            if isinstance(f.fix, SetColumnDefaultFix)
        )

        assert execute_plan(items).ok

        default = column_default_sql("examples_dbdefaultsexample", "created_at")
        assert default is not None
        assert "statement_timestamp" in default.lower()

        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()
        default_fixes = [i for i in items if isinstance(i.fix, SetColumnDefaultFix)]
        assert default_fixes == []
