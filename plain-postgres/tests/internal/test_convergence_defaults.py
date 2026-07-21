from __future__ import annotations

from app.examples.models.defaults import DBDefaultsExample, DefaultsExample
from conftest_convergence import column_default_sql, execute

from plain.postgres import get_connection
from plain.postgres.convergence import (
    analyze_model,
    can_auto_correct,
    execute_plan,
    plan_model_convergence,
)
from plain.postgres.convergence.analysis import (
    ColumnDefaultDrift,
    ColumnDefaultExpectedDrift,
    ColumnDefaultUndeclaredDrift,
    ColumnShouldBeNotNullDrift,
    DriftKind,
)
from plain.postgres.convergence.corrections import (
    DropColumnDefaultCorrection,
    SetColumnDefaultCorrection,
    SetNotNullCorrection,
)


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
            d for d in analysis.drifts if isinstance(d, ColumnDefaultExpectedDrift)
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
            d for d in analysis.drifts if isinstance(d, ColumnDefaultExpectedDrift)
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

    def test_no_drift_when_literal_default_matches(self, db):
        """Literal defaults persist on the column, and a matching DB DEFAULT
        produces no drift."""
        default = column_default_sql("examples_defaultsexample", "status")
        assert default is not None
        assert "pending" in default

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert default_drifts == []

    def test_no_drift_when_callable_default_stripped(self, db):
        """Callable defaults are evaluated in Python; Plain strips them from
        the column, so DB has no DEFAULT and there's no drift."""
        assert column_default_sql("examples_defaultsexample", "token") is None

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultDrift)
        ]
        assert default_drifts == []

    def test_detects_changed_literal_default(self, db):
        """DB has a different DEFAULT than the model's literal `default=` → CHANGED."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"status\" SET DEFAULT 'manual-default'"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultExpectedDrift)
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].kind == DriftKind.CHANGED
        assert default_drifts[0].column == "status"
        assert default_drifts[0].db_default_sql is not None
        assert "manual-default" in default_drifts[0].db_default_sql
        assert default_drifts[0].model_default_sql is not None
        assert "pending" in default_drifts[0].model_default_sql

    def test_detects_undeclared_default_on_undeclared_field(self, db):
        """Manual SET DEFAULT on a column whose model declares no default →
        UNDECLARED drift.  Plain owns column DEFAULTs; declare a default on
        the field to make it persistent."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"name\" SET DEFAULT 'manual-default'"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, DefaultsExample)

        default_drifts = [
            d for d in analysis.drifts if isinstance(d, ColumnDefaultUndeclaredDrift)
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].kind == DriftKind.UNDECLARED
        assert default_drifts[0].column == "name"
        assert default_drifts[0].db_default_sql is not None
        assert "manual-default" in default_drifts[0].db_default_sql


class TestColumnDefaultPlanning:
    def test_plans_set_default_for_missing(self, db):
        """MISSING drift → executable SetColumnDefaultCorrection."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, DBDefaultsExample)

        plan_items = [
            i
            for i in plan.executable()
            if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        assert len(plan_items) == 1
        correction = plan_items[0].correction
        assert isinstance(correction, SetColumnDefaultCorrection)
        assert correction.table == "examples_dbdefaultsexample"
        assert correction.column == "db_uuid"
        assert "gen_random_uuid()" in correction.default_sql

    def test_plans_set_default_for_changed(self, db):
        """CHANGED drift → executable SetColumnDefaultCorrection that overwrites."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" SET DEFAULT clock_timestamp()'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, DBDefaultsExample)

        plan_items = [
            i
            for i in plan.executable()
            if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        assert len(plan_items) == 1
        correction = plan_items[0].correction
        assert isinstance(correction, SetColumnDefaultCorrection)
        assert correction.column == "created_at"
        assert "statement_timestamp" in correction.default_sql.lower()

    def test_blocks_sync(self, db):
        """SetColumnDefaultCorrection blocks sync (correctness convergence)."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        plan_items = [
            i for i in items if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        assert len(plan_items) == 1
        assert plan_items[0].blocks_sync is True

    def test_can_auto_correct_missing(self):
        drift = ColumnDefaultExpectedDrift(
            table="t",
            column="c",
            kind=DriftKind.MISSING,
            model_default_sql="gen_random_uuid()",
        )
        assert can_auto_correct(drift)

    def test_can_auto_correct_changed(self):
        drift = ColumnDefaultExpectedDrift(
            table="t",
            column="c",
            kind=DriftKind.CHANGED,
            model_default_sql="gen_random_uuid()",
            db_default_sql="now()",
        )
        assert can_auto_correct(drift)

    def test_plans_drop_default_for_undeclared(self, db):
        """UNDECLARED drift → executable DropColumnDefaultCorrection."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"name\" SET DEFAULT 'manual-default'"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, DefaultsExample)

        plan_items = [
            i
            for i in plan.executable()
            if isinstance(i.correction, DropColumnDefaultCorrection)
        ]
        assert len(plan_items) == 1
        correction = plan_items[0].correction
        assert isinstance(correction, DropColumnDefaultCorrection)
        assert correction.column == "name"
        assert plan_items[0].blocks_sync is True

    def test_can_auto_correct_undeclared(self):
        drift = ColumnDefaultUndeclaredDrift(
            table="t",
            column="c",
            db_default_sql="'x'::text",
        )
        assert can_auto_correct(drift)


class TestColumnDefaultFixes:
    def test_apply_set_default(self, isolated_db):
        """SetColumnDefaultCorrection installs the provided SQL as the column DEFAULT."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is None

        correction = SetColumnDefaultCorrection(
            table="examples_dbdefaultsexample",
            column="db_uuid",
            default_sql="gen_random_uuid()",
        )
        sql = correction.apply()

        assert "SET DEFAULT gen_random_uuid()" in sql
        default = column_default_sql("examples_dbdefaultsexample", "db_uuid")
        assert default is not None
        assert "gen_random_uuid()" in default

    def test_apply_set_default_replaces_existing(self, isolated_db):
        """SetColumnDefaultCorrection overwrites an existing DEFAULT in one statement."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "created_at" SET DEFAULT clock_timestamp()'
        )

        correction = SetColumnDefaultCorrection(
            table="examples_dbdefaultsexample",
            column="created_at",
            default_sql="statement_timestamp()",
        )
        correction.apply()

        default = column_default_sql("examples_dbdefaultsexample", "created_at")
        assert default is not None
        assert "statement_timestamp" in default.lower()
        assert "clock_timestamp" not in default

    def test_apply_drop_default(self, isolated_db):
        """DropColumnDefaultCorrection removes the column DEFAULT."""
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is not None

        correction = DropColumnDefaultCorrection(
            table="examples_dbdefaultsexample", column="db_uuid"
        )
        sql = correction.apply()

        assert "DROP DEFAULT" in sql
        assert column_default_sql("examples_dbdefaultsexample", "db_uuid") is None

    def test_set_default_describe(self):
        correction = SetColumnDefaultCorrection(
            table="examples_dbdefaultsexample",
            column="db_uuid",
            default_sql="gen_random_uuid()",
        )
        assert (
            correction.describe()
            == "examples_dbdefaultsexample: set DEFAULT gen_random_uuid() on db_uuid"
        )

    def test_drop_default_describe(self):
        correction = DropColumnDefaultCorrection(
            table="examples_dbdefaultsexample", column="db_uuid"
        )
        assert (
            correction.describe()
            == "examples_dbdefaultsexample: drop DEFAULT on db_uuid"
        )

    def test_set_default_pass_order(self):
        """SetColumnDefaultCorrection runs at pass 2 alongside NOT NULL changes."""
        assert SetColumnDefaultCorrection.pass_order == 2

    def test_drop_default_pass_order(self):
        assert DropColumnDefaultCorrection.pass_order == 2


class TestColumnDefaultLifecycle:
    def test_drift_correction_end_to_end(self, isolated_db):
        """Manual DROP DEFAULT → detect MISSING → plan → execute → converged."""
        execute(
            'ALTER TABLE "examples_dbdefaultsexample" '
            'ALTER COLUMN "db_uuid" DROP DEFAULT'
        )

        conn = get_connection()

        # First pass: detect drift, plan correction
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        plan_items = [
            i for i in items if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        assert len(plan_items) == 1

        result = execute_plan(items)
        assert result.ok

        default = column_default_sql("examples_dbdefaultsexample", "db_uuid")
        assert default is not None
        assert "gen_random_uuid()" in default

        # Second pass: fully converged
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()
        default_fixes = [
            i for i in items if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        assert default_fixes == []

    def test_undeclared_default_end_to_end(self, isolated_db):
        """Manual SET DEFAULT on a column whose model declares no default →
        detect UNDECLARED → DROP → converged."""
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            "ALTER COLUMN \"name\" SET DEFAULT 'manual-default'"
        )
        assert column_default_sql("examples_defaultsexample", "name") is not None

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DefaultsExample).executable()

        drop_items = [
            i for i in items if isinstance(i.correction, DropColumnDefaultCorrection)
        ]
        assert len(drop_items) == 1

        result = execute_plan(items)
        assert result.ok
        assert column_default_sql("examples_defaultsexample", "name") is None

        # Second pass: fully converged
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DefaultsExample).executable()
        assert not [
            i for i in items if isinstance(i.correction, DropColumnDefaultCorrection)
        ]

    def test_column_carries_both_nullability_and_default_drifts(self, isolated_db):
        """A column with both kinds of drift populates `drifts` with both,
        and convergence applies both plan_items in one plan."""
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
        assert ColumnShouldBeNotNullDrift in drift_types
        assert ColumnDefaultExpectedDrift in drift_types

        # Plan carries both plan_items
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()

        correction_types = {type(item.correction) for item in items}
        assert SetNotNullCorrection in correction_types
        assert SetColumnDefaultCorrection in correction_types

        assert execute_plan(items).ok

        # Both plan_items applied — column is NOT NULL again and DEFAULT restored
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

        plan_items = [
            i for i in items if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        # Only `created_at` should need fixing; db_uuid already matches.
        assert any(
            f.correction.column == "created_at"
            for f in plan_items
            if isinstance(f.correction, SetColumnDefaultCorrection)
        )

        assert execute_plan(items).ok

        default = column_default_sql("examples_dbdefaultsexample", "created_at")
        assert default is not None
        assert "statement_timestamp" in default.lower()

        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, DBDefaultsExample).executable()
        default_fixes = [
            i for i in items if isinstance(i.correction, SetColumnDefaultCorrection)
        ]
        assert default_fixes == []
