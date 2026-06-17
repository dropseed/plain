from __future__ import annotations

import pytest
from app.examples.models.constraints import ConstraintExample
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
from plain.postgres.functions.text import Lower, Upper
from plain.postgres.introspection import ConType


def _create_exclusion_constraint(
    name: str = "examples_constraintexample_name_excl",
) -> None:
    execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    execute(
        f'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "{name}"'
        ' EXCLUDE USING gist ("name" WITH =)'
    )


class TestUnmanagedConstraintTypes:
    def test_exclusion_constraint_shown_as_unmanaged(self, db):
        """An exclusion constraint appears in constraints with no drift."""
        _create_exclusion_constraint()

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ConstraintExample)

        # No drift
        assert not any(
            getattr(d, "name", None) == "examples_constraintexample_name_excl"
            for d in analysis.drifts
        )

        # Appears in constraints with the right type
        excl = next(
            con
            for con in analysis.constraints
            if con.name == "examples_constraintexample_name_excl"
        )
        assert excl.constraint_type == ConType.EXCLUSION
        assert excl.issue is None
        assert excl.drift is None

    def test_exclusion_constraint_not_auto_dropped(self, db):
        """Convergence does not propose dropping unmanaged constraint types."""
        _create_exclusion_constraint()

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ConstraintExample).executable()

        assert not any(
            isinstance(item.fix, DropConstraintFix)
            and item.fix.name == "examples_constraintexample_name_excl"
            for item in items
        )

    def test_exclusion_constraint_not_counted_as_issue(self, db):
        """Unmanaged constraints don't count toward the issue total."""
        _create_exclusion_constraint()

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ConstraintExample)

        assert analysis.issue_count == 0


class TestDetectConstraintFixes:
    def test_no_fixes_when_converged(self, db):
        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ConstraintExample).executable()
        assert items == []

    def test_detects_extra_check_constraint(self, db):
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_test_check" CHECK ("id" >= 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ConstraintExample).executable()

        assert len(items) == 1
        assert isinstance(items[0].fix, DropConstraintFix)
        assert items[0].fix.name == "examples_constraintexample_test_check"

    def test_detects_extra_unique_constraint(self, db):
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_extra_unique" UNIQUE ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ConstraintExample).executable()

        assert len(items) == 1
        assert isinstance(items[0].fix, DropConstraintFix)
        assert items[0].fix.name == "examples_constraintexample_extra_unique"

    def test_detects_missing_check_constraint(self, db):
        original_constraints = list(ConstraintExample.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_constraintexample_id_nonneg",
        )
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)
            assert (
                items[0].fix.constraint.name == "examples_constraintexample_id_nonneg"
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_detects_missing_unique_constraint(self, db):
        execute(
            'ALTER TABLE "examples_constraintexample" DROP CONSTRAINT "unique_constraintexample_name_description"'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, ConstraintExample).executable()

        assert len(items) == 1
        assert isinstance(items[0].fix, AddConstraintFix)
        assert (
            items[0].fix.constraint.name == "unique_constraintexample_name_description"
        )

    def test_detects_not_valid_check_constraint(self, db):
        """A NOT VALID constraint in the DB that matches the model needs validation."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_constraintexample_id_nonneg",
        )
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, ValidateConstraintFix)
            assert items[0].fix.name == "examples_constraintexample_id_nonneg"
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_detects_check_constraint_definition_changed(self, db):
        """A check constraint with matching name but different expression is blocked."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        # Model declares CHECK (id >= 1)
        check = CheckConstraint(
            check=Q(id__gte=1),
            name="examples_constraintexample_id_nonneg",
        )
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        # DB has CHECK (id >= 0) — different expression, same name
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            # Changed constraint definition has no auto-fix
            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None
            assert plan.blocked[0].guidance is not None
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_no_false_positive_for_matching_check_constraint(self, db):
        """A check constraint with matching name and matching expression has no issues."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_constraintexample_id_nonneg",
        )
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        # DB has the same expression
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()

            assert items == []
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_detects_unique_constraint_definition_changed(self, db):
        """A unique constraint with matching name but different columns is blocked."""
        # DB already has unique_constraintexample_name_description on ("name", "description")
        # Model declares unique on ("name") only — same name, different columns
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            UniqueConstraint(
                fields=["name"], name="unique_constraintexample_name_description"
            ),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None
            assert plan.blocked[0].guidance is not None
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_no_false_positive_for_matching_unique_constraint(self, db):
        """A unique constraint with matching name and matching columns has no issues."""
        conn = get_connection()
        with conn.cursor() as cursor:
            plan = plan_model_convergence(conn, cursor, ConstraintExample)

        # The existing unique_constraintexample_name_description on ("name", "description") matches the model
        assert plan.executable() == []
        assert plan.blocked == []

    def test_detects_unique_deferrable_changed(self, db):
        """Same columns but different deferrable setting is a definition change."""
        # DB has non-deferrable unique_constraintexample_name_description; model declares it deferrable
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            UniqueConstraint(
                fields=["name", "description"],
                name="unique_constraintexample_name_description",
                deferrable=Deferrable.DEFERRED,
            ),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_detects_unique_include_changed(self, isolated_db):
        """Same columns but added INCLUDE column is a definition change."""
        # Drop the existing constraint and recreate with INCLUDE
        execute(
            'ALTER TABLE "examples_constraintexample" DROP CONSTRAINT "unique_constraintexample_name_description"'
        )
        execute(
            'CREATE UNIQUE INDEX "unique_constraintexample_name_description" ON "examples_constraintexample" ("name", "description")'
        )
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "unique_constraintexample_name_description"'
            ' UNIQUE USING INDEX "unique_constraintexample_name_description"'
        )

        # Model now expects INCLUDE ("id") — DB has no INCLUDE
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            UniqueConstraint(
                fields=["name", "description"],
                name="unique_constraintexample_name_description",
                include=["id"],
            ),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
        finally:
            ConstraintExample.model_options.constraints = original_constraints


class TestApplyConstraintFixes:
    def test_add_check_constraint_validates_immediately(self, isolated_db):
        """AddConstraintFix for check constraints adds NOT VALID and validates in one apply."""
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_constraintexample_id_nonneg",
        )
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        try:
            fix = AddConstraintFix(
                table="examples_constraintexample",
                constraint=check,
                model=ConstraintExample,
            )
            sql = fix.apply()

            assert "NOT VALID" in sql
            assert "VALIDATE CONSTRAINT" in sql
            assert constraint_exists(
                "examples_constraintexample", "examples_constraintexample_id_nonneg"
            )
            assert constraint_is_valid(
                "examples_constraintexample", "examples_constraintexample_id_nonneg"
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_validate_constraint(self, isolated_db):
        """ValidateConstraintFix validates a NOT VALID constraint."""
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )
        assert not constraint_is_valid(
            "examples_constraintexample", "examples_constraintexample_id_nonneg"
        )

        fix = ValidateConstraintFix(
            table="examples_constraintexample",
            name="examples_constraintexample_id_nonneg",
        )
        fix.apply()

        assert constraint_is_valid(
            "examples_constraintexample", "examples_constraintexample_id_nonneg"
        )

    def test_full_check_constraint_lifecycle(self, isolated_db):
        """A single converge pass adds and validates a check constraint."""
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_constraintexample_id_nonneg",
        )
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)

            items[0].fix.apply()
            assert constraint_is_valid(
                "examples_constraintexample", "examples_constraintexample_id_nonneg"
            )

            # Second pass: fully converged
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()
            assert items == []
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    @pytest.mark.parametrize(
        "check",
        [
            Q(name__in=["a", "b"]),
            Q(name="a") | Q(name="b"),
        ],
        ids=["__in lookup", "OR of equals"],
    )
    def test_membership_check_constraint_no_drift_on_resync(self, isolated_db, check):
        """Regression for #67: a CheckConstraint using `__in` (or its
        `Q | Q` equivalent) shouldn't be flagged as drifted on subsequent
        sync runs. PG stores `IN (...)` as `= ANY (ARRAY[...])` and the
        per-disjunct grouping in `OR` adds extra parens — both must
        normalize to the same form as the ORM-generated SQL."""
        constraint = CheckConstraint(
            check=check, name="examples_constraintexample_name_membership"
        )
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)
            items[0].fix.apply()

            # Second pass: must report no drift, neither executable nor
            # blocked. PG stores `IN (...)` as `= ANY (ARRAY[...])` and adds
            # per-disjunct parens around `OR` operands; the round-trip lets
            # PG normalize both sides through the same deparser.
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)
            assert plan.executable() == []
            assert plan.blocked == []
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_normalization_falls_back_when_live_shape_incompatible(self, db):
        """When the model declares a CheckConstraint that's incompatible
        with the live table shape (e.g. references a column that doesn't
        exist on the live table), the round-trip ALTER raises in PG. The
        helper must catch and return a sentinel so convergence still
        reports drift instead of crashing — a real concern for `analyze`
        / doctor on a half-migrated DB."""
        from plain.postgres.convergence.analysis import (
            _normalize_constraint_def,
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            # Reference a column that doesn't exist on the live table.
            result = _normalize_constraint_def(
                cursor,
                ConstraintExample,
                "CHECK (nonexistent_col > 0)",
            )
            assert result == ""
            # Cursor must remain usable after the failed normalization —
            # the savepoint inside _probe_table must roll back cleanly.
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
            # And a subsequent valid normalization on the same cursor must
            # still succeed — proves the rollback is complete, not just that
            # the cursor accepts trivial follow-up queries.
            valid = _normalize_constraint_def(
                cursor,
                ConstraintExample,
                "CHECK (length(name) > 0)",
            )
            assert valid.startswith("CHECK ")

    def test_normalization_falls_back_on_data_error(self, db):
        """`SET DEFAULT 'abc'` on an int column raises DataError, not
        ProgrammingError — the catch must include DataError so analyze
        on a half-migrated DB doesn't crash on type mismatches."""
        from plain.postgres.convergence.analysis import (
            _normalize_default_expr,
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            # ConstraintExample has `id` as integer; setting a text literal
            # default on it raises psycopg.errors.InvalidTextRepresentation
            # (DataError subclass).
            result = _normalize_default_expr(cursor, ConstraintExample, "id", "'abc'")
            assert result == ""
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

    def test_normalization_propagates_privilege_errors(self, db):
        """`InsufficientPrivilege` (raised when the role lacks CREATE TEMP)
        must NOT be swallowed into the empty-sentinel fallback. Otherwise
        analyze on a privilege-restricted role floods the user with false
        "definition differs: DB has ..." reports for every index/constraint
        instead of surfacing the configuration problem. Regression for the
        broad-`ProgrammingError` catch the rewrite started with.

        Patches `_probe_table` to raise the privilege error so the test
        doesn't depend on a separately provisioned restricted role."""
        from contextlib import contextmanager
        from unittest.mock import patch

        import psycopg

        from plain.postgres.convergence.analysis import (
            _normalize_constraint_def,
            _normalize_default_expr,
            _normalize_index_def,
        )

        @contextmanager
        def _raising_probe_table(*args, **kwargs):
            raise psycopg.errors.InsufficientPrivilege(
                "permission denied for schema pg_temp"
            )
            yield  # pragma: no cover — never reached

        conn = get_connection()

        # Patch every helper's `_probe_table` and verify the privilege
        # error propagates instead of returning the empty sentinel.
        with patch(
            "plain.postgres.convergence.analysis._probe_table",
            _raising_probe_table,
        ):
            with conn.cursor() as cursor:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    _normalize_constraint_def(
                        cursor, ConstraintExample, "CHECK (length(name) > 0)"
                    )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    _normalize_default_expr(cursor, ConstraintExample, "name", "'x'")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    _normalize_index_def(
                        cursor,
                        ConstraintExample,
                        fields_orders=[("name", "")],
                    )

    def test_normalization_does_not_drop_real_user_table(self, isolated_db):
        """The round-trip helper uses a fixed temp-table name
        `_plain_convergence_probe`. It must never resolve via `search_path` to
        a real user table that happens to share the name — qualifying every
        cleanup DROP with the `pg_temp` schema keeps the normalization
        isolated to the session's own temp namespace."""
        execute('CREATE TABLE "_plain_convergence_probe" (id integer)')
        execute('INSERT INTO "_plain_convergence_probe" (id) VALUES (1)')

        constraint = CheckConstraint(
            check=Q(name__in=["a", "b"]),
            name="examples_constraintexample_normalize_safe",
        )
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                # Triggers the round-trip helpers via _compare_check_constraints.
                plan_model_convergence(conn, cursor, ConstraintExample)

            # The real public._plain_convergence_probe must still be there
            # with its row.
            with conn.cursor() as cursor:
                cursor.execute('SELECT id FROM "_plain_convergence_probe"')
                rows = cursor.fetchall()
            assert rows == [(1,)]
        finally:
            ConstraintExample.model_options.constraints = original_constraints
            execute('DROP TABLE IF EXISTS "_plain_convergence_probe"')

    def test_check_drift_diagnostic_when_normalization_fails(self, isolated_db):
        """When `_normalize_constraint_def` returns "" (e.g. half-migrated
        DB where the model SQL is incompatible with the live shape), the
        higher-level constraint compare must still emit a CHANGED status
        with the abridged "definition differs: DB has ..." message — no
        "model expects ..." half, since the normalized model text is
        unavailable. Patches the normalizer to force the empty-sentinel
        path without needing a live type mismatch."""
        from unittest.mock import patch

        original_constraints = list(ConstraintExample.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_constraintexample_id_check",
        )
        ConstraintExample.model_options.constraints = [*original_constraints, check]
        # DB has the matching name but a different definition.
        execute(
            'ALTER TABLE "examples_constraintexample" '
            'ADD CONSTRAINT "examples_constraintexample_id_check" '
            'CHECK ("id" >= 1)'
        )

        try:
            with patch(
                "plain.postgres.convergence.analysis._normalize_constraint_def",
                return_value="",
            ):
                conn = get_connection()
                with conn.cursor() as cursor:
                    analysis = analyze_model(conn, cursor, ConstraintExample)

            status = next(
                c
                for c in analysis.constraints
                if c.name == "examples_constraintexample_id_check"
            )
            assert isinstance(status.drift, ConstraintDrift)
            assert status.drift.kind == DriftKind.CHANGED
            # Abridged diagnostic: DB text shown, model side omitted.
            assert status.issue is not None
            assert "DB has" in status.issue
            assert "CHECK" in status.issue
            assert "model expects" not in status.issue
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_unique_drift_diagnostic_when_normalization_fails(self, isolated_db):
        """Same fallback path as the check-constraint case but for unique
        constraints. The model-text-omitted form of the diagnostic must
        also fire here so analyze on a half-migrated DB never crashes."""
        from unittest.mock import patch

        original_constraints = list(ConstraintExample.model_options.constraints)
        # Model declares UNIQUE on (name) — column-based, deparse path.
        constraint = UniqueConstraint(
            fields=["name"],
            name="examples_constraintexample_unique_normalize",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]
        # DB has the matching name but UNIQUE on (description) — different.
        execute(
            'ALTER TABLE "examples_constraintexample" '
            'ADD CONSTRAINT "examples_constraintexample_unique_normalize" '
            'UNIQUE ("description")'
        )

        try:
            with patch(
                "plain.postgres.convergence.analysis._normalize_constraint_def",
                return_value="",
            ):
                conn = get_connection()
                with conn.cursor() as cursor:
                    analysis = analyze_model(conn, cursor, ConstraintExample)

            status = next(
                c
                for c in analysis.constraints
                if c.name == "examples_constraintexample_unique_normalize"
            )
            assert isinstance(status.drift, ConstraintDrift)
            assert status.drift.kind == DriftKind.CHANGED
            assert status.issue is not None
            assert "DB has" in status.issue
            assert "UNIQUE" in status.issue
            assert "model expects" not in status.issue
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_check_definition_change_is_blocked(self, isolated_db):
        """Changed check definition is blocked — no auto-fix available."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        # Model declares CHECK (id >= 1)
        check = CheckConstraint(
            check=Q(id__gte=1),
            name="examples_constraintexample_id_nonneg",
        )
        ConstraintExample.model_options.constraints = [*original_constraints, check]

        # DB has CHECK (id >= 0) — old expression
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()

            # Detects definition change as blocked (no executable fix)
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None

            # can_auto_fix returns False for changed constraints
            assert not can_auto_fix(plan.blocked[0].drift)
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_unique_definition_change_is_blocked(self, isolated_db):
        """Changed unique columns is blocked — no auto-fix available."""
        # DB has unique_constraintexample_name_description on ("name", "description")
        # Model declares unique on ("name") only — same name, different columns
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            UniqueConstraint(
                fields=["name"], name="unique_constraintexample_name_description"
            ),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None

            assert not can_auto_fix(plan.blocked[0].drift)
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_apply_drop_constraint(self, isolated_db):
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_temp_check" CHECK ("id" >= 0)'
        )
        assert constraint_exists(
            "examples_constraintexample", "examples_constraintexample_temp_check"
        )

        fix = DropConstraintFix(
            table="examples_constraintexample",
            name="examples_constraintexample_temp_check",
        )
        fix.apply()

        assert not constraint_exists(
            "examples_constraintexample", "examples_constraintexample_temp_check"
        )

    def test_add_unique_using_index(self, isolated_db):
        """Unique constraints use CONCURRENTLY + USING INDEX."""
        # Drop the constraint AND its backing index
        execute(
            'ALTER TABLE "examples_constraintexample" DROP CONSTRAINT "unique_constraintexample_name_description"'
        )
        assert not constraint_exists(
            "examples_constraintexample", "unique_constraintexample_name_description"
        )

        constraint = None
        for c in ConstraintExample.model_options.constraints:
            if c.name == "unique_constraintexample_name_description":
                constraint = c
                break
        assert constraint is not None

        fix = AddConstraintFix(
            table="examples_constraintexample",
            constraint=constraint,
            model=ConstraintExample,
        )
        sql = fix.apply()

        assert "CONCURRENTLY" in sql
        assert "USING INDEX" in sql
        assert constraint_exists(
            "examples_constraintexample", "unique_constraintexample_name_description"
        )

    @pytest.mark.parametrize(
        "deferrable",
        [Deferrable.DEFERRED, Deferrable.IMMEDIATE],
        ids=["deferred", "immediate"],
    )
    def test_add_deferrable_unique_constraint(self, isolated_db, deferrable):
        """Deferrable unique constraints include the appropriate DEFERRABLE clause."""
        constraint = UniqueConstraint(
            fields=["name"],
            name=f"examples_constraintexample_name_{deferrable.value}",
            deferrable=deferrable,
        )
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        try:
            fix = AddConstraintFix(
                table="examples_constraintexample",
                constraint=constraint,
                model=ConstraintExample,
            )
            sql = fix.apply()

            assert f"DEFERRABLE INITIALLY {deferrable.name}" in sql
            assert constraint_exists("examples_constraintexample", constraint.name)
            assert constraint_is_deferrable(
                "examples_constraintexample", constraint.name
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints


class TestConstraintRename:
    def test_rename_check_constraint(self, db):
        """A missing + extra check constraint with same expression is a rename."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            CheckConstraint(
                check=Q(id__gte=0), name="examples_constraintexample_id_new"
            ),
        ]
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_old"'
            ' CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, ConstraintExample)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, ConstraintDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_constraintexample_id_old"
            assert rename_drifts[0].new_name == "examples_constraintexample_id_new"

            assert not any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, ConstraintDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_rename_unique_constraint(self, db):
        """A missing + extra unique constraint with same columns is a rename."""
        execute(
            'ALTER TABLE "examples_constraintexample" DROP CONSTRAINT "unique_constraintexample_name_description"'
        )
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "old_unique_constraintexample_name_description"'
            ' UNIQUE ("name", "description")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, ConstraintExample)

        rename_drifts = [
            d
            for d in analysis.drifts
            if isinstance(d, ConstraintDrift) and d.kind == DriftKind.RENAMED
        ]
        assert len(rename_drifts) == 1
        assert (
            rename_drifts[0].old_name == "old_unique_constraintexample_name_description"
        )
        assert rename_drifts[0].new_name == "unique_constraintexample_name_description"

    def test_no_rename_when_expression_differs(self, db):
        """Different check expressions means separate add + drop, not rename."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            CheckConstraint(
                check=Q(id__gte=1), name="examples_constraintexample_id_new"
            ),
        ]
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_old"'
            ' CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, ConstraintExample)

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
            ConstraintExample.model_options.constraints = original_constraints

    def test_apply_rename_constraint(self, isolated_db):
        """RenameConstraintFix renames using ALTER TABLE RENAME CONSTRAINT."""
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "old_check" CHECK ("id" >= 0)'
        )
        assert constraint_exists("examples_constraintexample", "old_check")

        fix = RenameConstraintFix(
            table="examples_constraintexample",
            old_name="old_check",
            new_name="new_check",
        )
        sql = fix.apply()

        assert "RENAME CONSTRAINT" in sql
        assert not constraint_exists("examples_constraintexample", "old_check")
        assert constraint_exists("examples_constraintexample", "new_check")

    def test_rename_unique_renames_backing_index(self, isolated_db):
        """Renaming a unique constraint also renames its backing index."""
        execute(
            'ALTER TABLE "examples_constraintexample" DROP CONSTRAINT "unique_constraintexample_name_description"'
        )
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "old_unique"'
            ' UNIQUE ("name", "description")'
        )
        assert constraint_exists("examples_constraintexample", "old_unique")
        assert index_exists("old_unique")

        fix = RenameConstraintFix(
            table="examples_constraintexample",
            old_name="old_unique",
            new_name="new_unique",
        )
        fix.apply()

        assert constraint_exists("examples_constraintexample", "new_unique")
        assert index_exists("new_unique")
        assert not constraint_exists("examples_constraintexample", "old_unique")
        assert not index_exists("old_unique")

    def test_rename_constraint_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            CheckConstraint(
                check=Q(id__gte=0), name="examples_constraintexample_id_new"
            ),
        ]
        execute(
            'ALTER TABLE "examples_constraintexample" ADD CONSTRAINT "examples_constraintexample_id_old"'
            ' CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()

            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, RenameConstraintFix)

            items[0].fix.apply()

            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()
            assert items == []
        finally:
            ConstraintExample.model_options.constraints = original_constraints


class TestIndexBackedUniqueConstraints:
    """Tests for UniqueConstraint variants that PostgreSQL can only store as
    indexes (condition, expressions, opclasses).  These must go through the
    index creation path, not the constraint attachment path."""

    # -- Gap 1: AddConstraintFix should not try USING INDEX for these --

    def test_add_conditional_unique_succeeds(self, isolated_db):
        """A conditional unique constraint should be created as an index, not fail."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["name"],
            condition=Q(description__isnull=False),
            name="examples_constraintexample_name_conditional_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()

            # Should produce a fix
            assert len(items) >= 1
            fix = next(
                i.fix for i in items if getattr(i.fix, "constraint", None) is constraint
            )
            assert fix is not None
            sql = fix.apply()
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_constraintexample_name_conditional_uq")
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_add_expression_unique_succeeds(self, isolated_db):
        """An expression-based unique constraint should be created as an index."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            Upper("name"),
            name="examples_constraintexample_name_upper_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()

            assert len(items) >= 1
            fix = next(
                i.fix for i in items if getattr(i.fix, "constraint", None) is constraint
            )
            assert fix is not None
            sql = fix.apply()
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_constraintexample_name_upper_uq")
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    # -- Gap 2: matching index-backed unique should not produce false drift --

    def test_matching_conditional_unique_no_drift(self, db):
        """An existing partial unique index matching the model has no issues."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["name"],
            condition=Q(description__isnull=False),
            name="examples_constraintexample_name_partial_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        # Create the index using the model's own to_sql so the definition matches
        execute(constraint.to_sql(ConstraintExample))

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            # Should be fully converged — no missing, no changed
            constraint_drifts = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift)
                and d.drift.constraint is not None
                and d.drift.constraint.name
                == "examples_constraintexample_name_partial_uq"
            ]
            assert constraint_drifts == [], (
                f"Expected no drift for matching partial unique, got: "
                f"{[d.describe() for d in constraint_drifts]}"
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_matching_expression_unique_no_drift(self, db):
        """An existing expression unique index matching the model has no issues."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            Upper("name"),
            name="examples_constraintexample_name_upper_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        execute(
            'CREATE UNIQUE INDEX "examples_constraintexample_name_upper_uq"'
            ' ON "examples_constraintexample" (UPPER("name"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            constraint_drifts = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift)
                and d.drift.constraint is not None
                and d.drift.constraint.name
                == "examples_constraintexample_name_upper_uq"
            ]
            assert constraint_drifts == [], (
                f"Expected no drift for matching expression unique, got: "
                f"{[d.describe() for d in constraint_drifts]}"
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_matching_expression_with_condition_no_drift(self, db):
        """Expression unique with a WHERE clause should not report false-positive drift.

        PG adds type casts (e.g. ''::text) and the ORM adds extra parens around
        expressions.  Structured comparison handles both.
        """
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            Lower("name"),
            condition=~Q(name=""),
            name="examples_constraintexample_name_lower_cond_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        execute(constraint.to_sql(ConstraintExample))

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            constraint_drifts = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift)
                and d.drift.constraint is not None
                and d.drift.constraint.name
                == "examples_constraintexample_name_lower_cond_uq"
            ]
            assert constraint_drifts == [], (
                f"Expected no drift for matching expression+condition unique, got: "
                f"{[d.describe() for d in constraint_drifts]}"
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    # -- Gap 3: full lifecycle converges (create → re-check → no work) --

    def test_conditional_unique_lifecycle(self, isolated_db):
        """Create conditional unique → re-check → converged (no perpetual failure)."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["name"],
            condition=Q(description__isnull=False),
            name="examples_constraintexample_name_partial_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        try:
            conn = get_connection()

            # First pass: creates the index
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, ConstraintExample
                ).executable()
            assert any(getattr(i.fix, "constraint", None) is constraint for i in items)
            for item in items:
                if getattr(item.fix, "constraint", None) is constraint:
                    assert item.fix is not None
                    item.fix.apply()

            # Second pass: should be fully converged
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            remaining = [
                d
                for d in plan.items
                if isinstance(d.drift, ConstraintDrift | IndexDrift)
                and getattr(d.drift, "name", None)
                == "examples_constraintexample_name_partial_uq"
            ]
            assert remaining == [], (
                f"Expected convergence after creation, got: "
                f"{[d.drift.describe() for d in remaining]}"
            )
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    # -- Gap 4: condition/opclass changes detected as CHANGED --

    def test_detects_condition_change_on_partial_unique(self, db):
        """Same name and columns but different WHERE clause is a definition change."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        # Model declares WHERE (description IS NOT NULL)
        constraint = UniqueConstraint(
            fields=["name"],
            condition=Q(description__isnull=False),
            name="examples_constraintexample_name_partial_uq",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        # DB has a different condition: WHERE (id > 100)
        execute(
            'CREATE UNIQUE INDEX "examples_constraintexample_name_partial_uq"'
            ' ON "examples_constraintexample" ("name")'
            ' WHERE ("id" > 100)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            assert plan.executable() == []
            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    # -- Gap 5: rename/drop use correct fix types for index-only --

    def test_undeclared_index_only_unique_uses_drop_index(self, db):
        """Undeclared index-only unique should use DropIndexFix, not DropConstraintFix."""
        from plain.postgres.convergence import DropIndexFix

        execute(
            'CREATE UNIQUE INDEX "examples_constraintexample_old_partial_uq"'
            ' ON "examples_constraintexample" ("name")'
            ' WHERE ("id" > 0)'
        )

        plan = plan_convergence()
        undeclared = [
            item
            for item in plan.items
            if isinstance(item.drift, IndexDrift)
            and item.drift.kind == DriftKind.UNDECLARED
            and item.drift.name == "examples_constraintexample_old_partial_uq"
        ]
        assert len(undeclared) == 1
        assert isinstance(undeclared[0].fix, DropIndexFix)

    def test_rename_index_only_unique_uses_rename_index(self, db):
        """Renaming an index-only unique should use RenameIndexFix."""
        from plain.postgres.convergence import RenameIndexFix

        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["name"],
            condition=Q(description__isnull=False),
            name="examples_constraintexample_name_partial_new",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        # Create the matching index under the old name
        execute(constraint.to_sql(ConstraintExample).replace("_new", "_old"))

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, ConstraintExample)

            rename_items = [
                item
                for item in plan.items
                if isinstance(item.drift, IndexDrift)
                and item.drift.kind == DriftKind.RENAMED
            ]
            assert len(rename_items) == 1
            assert isinstance(rename_items[0].fix, RenameIndexFix)
        finally:
            ConstraintExample.model_options.constraints = original_constraints

    def test_no_rename_when_condition_differs(self, db):
        """Same columns + different condition + different name is NOT a rename."""
        original_constraints = list(ConstraintExample.model_options.constraints)
        constraint = UniqueConstraint(
            fields=["name"],
            condition=Q(id__gt=0),
            name="examples_constraintexample_name_partial_new",
        )
        ConstraintExample.model_options.constraints = [
            *original_constraints,
            constraint,
        ]

        # DB has the same columns but a different condition
        execute(
            'CREATE UNIQUE INDEX "examples_constraintexample_name_partial_old"'
            ' ON "examples_constraintexample" ("name")'
            ' WHERE ("id" > 100)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, ConstraintExample)

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
            ConstraintExample.model_options.constraints = original_constraints
