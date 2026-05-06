from __future__ import annotations

from app.examples.models.relationships import Widget, WidgetTag
from conftest_convergence import constraint_exists, create_invalid_index, execute

from plain.postgres import CheckConstraint, Index, Q, get_connection
from plain.postgres.convergence import (
    AddConstraintFix,
    ConstraintDrift,
    CreateIndexFix,
    DriftKind,
    DropConstraintFix,
    DropIndexFix,
    IndexDrift,
    PlanItem,
    RebuildIndexFix,
    RenameIndexFix,
    ValidateConstraintFix,
    analyze_model,
    can_auto_fix,
    execute_plan,
    plan_convergence,
    plan_model_convergence,
)
from plain.postgres.functions.text import Upper


class TestPassOrdering:
    def test_fixes_sorted_by_pass(self, db):
        """plan_convergence() returns items in pass order: rebuild, create indexes,
        add constraints, validate, drop constraints, drop indexes."""
        original_indexes = list(Widget.model_options.indexes)
        original_constraints = list(Widget.model_options.constraints)

        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_idx"),
            Index(fields=["size"], name="examples_widget_size_idx"),
        ]
        Widget.model_options.constraints = [
            *original_constraints,
            CheckConstraint(check=Q(id__gte=0), name="examples_widget_id_nonneg"),
            CheckConstraint(check=Q(id__lte=999999), name="examples_widget_id_max"),
        ]

        create_invalid_index("examples_widget_size_idx")
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_id_max"'
            ' CHECK ("id" <= 999999) NOT VALID'
        )
        execute(
            'CREATE INDEX "examples_widget_extra_idx" ON "examples_widget" ("size")'
        )
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_extra_check" CHECK ("id" >= -1)'
        )

        try:
            items = plan_convergence().executable()
            fix_types = [type(item.fix) for item in items]

            # All six fix types should be present
            assert RebuildIndexFix in fix_types
            assert CreateIndexFix in fix_types
            assert AddConstraintFix in fix_types
            assert ValidateConstraintFix in fix_types
            assert DropConstraintFix in fix_types
            assert DropIndexFix in fix_types

            # Verify full pass ordering
            rebuild_idx = max(
                i for i, t in enumerate(fix_types) if t is RebuildIndexFix
            )
            create_idx = max(i for i, t in enumerate(fix_types) if t is CreateIndexFix)
            add_con_max = max(
                i for i, t in enumerate(fix_types) if t is AddConstraintFix
            )
            validate_min = min(
                i for i, t in enumerate(fix_types) if t is ValidateConstraintFix
            )
            validate_max = max(
                i for i, t in enumerate(fix_types) if t is ValidateConstraintFix
            )
            drop_con_min = min(
                i for i, t in enumerate(fix_types) if t is DropConstraintFix
            )
            drop_con_max = max(
                i for i, t in enumerate(fix_types) if t is DropConstraintFix
            )
            drop_idx = min(i for i, t in enumerate(fix_types) if t is DropIndexFix)

            assert rebuild_idx < create_idx
            assert create_idx < add_con_max
            assert add_con_max < validate_min
            assert validate_max < drop_con_min
            assert drop_con_max < drop_idx
        finally:
            Widget.model_options.indexes = original_indexes
            Widget.model_options.constraints = original_constraints


class TestFixFailureRecovery:
    def test_failed_fix_continues(self, isolated_db):
        """A failed fix rolls back, and the next fix still succeeds."""
        # Add a real constraint to drop
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_real_check" CHECK ("id" >= 0)'
        )
        assert constraint_exists("examples_widget", "examples_widget_real_check")

        fixes = [
            # This one will fail — constraint doesn't exist
            DropConstraintFix(table="examples_widget", name="nonexistent_constraint"),
            # This one should still succeed
            DropConstraintFix(
                table="examples_widget", name="examples_widget_real_check"
            ),
        ]

        results = []
        for fix in fixes:
            try:
                fix.apply()
                results.append("ok")
            except Exception:
                results.append("failed")

        assert results == ["failed", "ok"]
        assert not constraint_exists("examples_widget", "examples_widget_real_check")


class TestAnalyzeModel:
    """Tests for the unified analysis layer (analyze_model)."""

    def test_rename_detection(self, db):
        """A missing index + extra index with same columns is detected as a rename."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_new_idx"),
        ]
        execute(
            'CREATE INDEX "examples_widget_name_old_idx" ON "examples_widget" ("name")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_widget_name_old_idx"
            assert rename_drifts[0].new_name == "examples_widget_name_new_idx"

            # No separate create or drop drifts
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )

            # Schema shows the rename as a single index entry
            renamed = [
                idx
                for idx in analysis.indexes
                if idx.name == "examples_widget_name_new_idx"
            ]
            assert len(renamed) == 1
            assert renamed[0].issue == "rename from examples_widget_name_old_idx"
            assert renamed[0].drift is not None
            assert renamed[0].drift.kind == DriftKind.RENAMED
        finally:
            Widget.model_options.indexes = original_indexes

    def test_rename_with_fk_columns(self, db):
        """Rename detection resolves model field names to DB column names."""
        original_indexes = list(WidgetTag.model_options.indexes)
        # Model field is "widget", DB column is "widget_id"
        WidgetTag.model_options.indexes = [
            *original_indexes,
            Index(fields=["widget"], name="examples_widgettag_widget_new_idx"),
        ]
        execute(
            'CREATE INDEX "examples_widgettag_widget_old_idx"'
            ' ON "examples_widgettag" ("widget_id")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, WidgetTag)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_widgettag_widget_old_idx"
            assert rename_drifts[0].new_name == "examples_widgettag_widget_new_idx"
        finally:
            WidgetTag.model_options.indexes = original_indexes

    def test_rename_multi_column(self, db):
        """Rename detection works for multi-column indexes."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name", "size"], name="examples_widget_name_size_new_idx"),
        ]
        execute(
            'CREATE INDEX "examples_widget_name_size_old_idx"'
            ' ON "examples_widget" ("name", "size")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_widget_name_size_old_idx"
            assert rename_drifts[0].new_name == "examples_widget_name_size_new_idx"
        finally:
            Widget.model_options.indexes = original_indexes

    def test_no_rename_when_columns_differ(self, db):
        """Different columns means separate create + drop, not a rename."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["size"], name="examples_widget_size_idx"),
        ]
        execute(
            'CREATE INDEX "examples_widget_extra_idx" ON "examples_widget" ("name")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            assert any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
                for d in analysis.drifts
            )
        finally:
            Widget.model_options.indexes = original_indexes

    def test_no_rename_when_ambiguous(self, db):
        """Two missing + two extra with same columns: no rename, all create/drop."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_idx_a"),
            Index(fields=["name"], name="examples_widget_idx_b"),
        ]
        execute('CREATE INDEX "examples_widget_old_a" ON "examples_widget" ("name")')
        execute('CREATE INDEX "examples_widget_old_b" ON "examples_widget" ("name")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
                for d in analysis.drifts
            )
            missing_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
            ]
            undeclared_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
            ]
            assert len(missing_drifts) == 2
            assert len(undeclared_drifts) == 2
        finally:
            Widget.model_options.indexes = original_indexes

    def test_rename_expression_index(self, db):
        """Expression-based indexes are matched by normalized definition."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(Upper("name"), name="examples_widget_name_upper_new_idx"),
        ]
        execute(
            'CREATE INDEX "examples_widget_name_upper_old_idx"'
            ' ON "examples_widget" (UPPER("name"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 1
            assert rename_drifts[0].old_name == "examples_widget_name_upper_old_idx"
            assert rename_drifts[0].new_name == "examples_widget_name_upper_new_idx"

            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.MISSING
                for d in analysis.drifts
            )
            assert not any(
                isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
                for d in analysis.drifts
            )
        finally:
            Widget.model_options.indexes = original_indexes

    def test_fixable_index_annotated(self, db):
        """A missing index has a drift on its IndexStatus."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            missing = [
                idx
                for idx in analysis.indexes
                if idx.name == "examples_widget_name_idx"
            ]
            assert len(missing) == 1
            assert missing[0].issue is not None
            assert missing[0].drift is not None
            assert missing[0].drift.kind == DriftKind.MISSING
        finally:
            Widget.model_options.indexes = original_indexes

    def test_plan_model_convergence(self, db):
        """plan_model_convergence() returns a plan with correct items."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Widget).executable()

            assert isinstance(items, list)
            assert len(items) == 1
            assert isinstance(items[0].fix, CreateIndexFix)
        finally:
            Widget.model_options.indexes = original_indexes

    def test_issue_count(self, db):
        """ModelAnalysis.issue_count counts issues correctly."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, Widget)

            # Missing index = 1 issue
            assert analysis.issue_count >= 1
            missing = [
                idx
                for idx in analysis.indexes
                if idx.name == "examples_widget_name_idx"
            ]
            assert len(missing) == 1
            assert missing[0].issue is not None
        finally:
            Widget.model_options.indexes = original_indexes


class TestDriftPolicy:
    """Tests for blocks_sync and DriftKind policy via PlanItem."""

    def test_index_fixes_do_not_block_sync(self, db):
        """Index operations (create, rebuild, rename) do not block sync."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Widget).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, CreateIndexFix)
            assert items[0].blocks_sync is False
        finally:
            Widget.model_options.indexes = original_indexes

    def test_constraint_add_blocks_sync(self, db):
        """Adding a missing constraint blocks sync."""
        original_constraints = list(Widget.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_widget_id_nonneg",
        )
        Widget.model_options.constraints = [*original_constraints, check]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Widget).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, AddConstraintFix)
            assert items[0].blocks_sync is True
        finally:
            Widget.model_options.constraints = original_constraints

    def test_constraint_validate_blocks_sync(self, db):
        """Validating a NOT VALID constraint blocks sync."""
        original_constraints = list(Widget.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=0),
            name="examples_widget_id_nonneg",
        )
        Widget.model_options.constraints = [*original_constraints, check]
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_id_nonneg" CHECK ("id" >= 0) NOT VALID'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Widget).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, ValidateConstraintFix)
            assert items[0].blocks_sync is True
        finally:
            Widget.model_options.constraints = original_constraints

    def test_rename_does_not_block_sync(self, db):
        """Renames (index and constraint) do not block sync."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_new_idx"),
        ]
        execute(
            'CREATE INDEX "examples_widget_name_old_idx" ON "examples_widget" ("name")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Widget).executable()

            assert len(items) == 1
            assert isinstance(items[0].fix, RenameIndexFix)
            assert items[0].blocks_sync is False
        finally:
            Widget.model_options.indexes = original_indexes

    def test_undeclared_constraint_included_in_plan(self, db):
        """Undeclared constraints are auto-dropped."""
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_test_check" CHECK ("id" >= 0)'
        )

        plan = plan_convergence()
        items = plan.executable()
        drops = [item for item in items if isinstance(item.fix, DropConstraintFix)]
        assert len(drops) == 1
        assert drops[0].blocks_sync is True

    def test_undeclared_index_included_in_plan(self, db):
        """Undeclared indexes are auto-dropped."""
        execute(
            'CREATE INDEX "examples_widget_extra_idx" ON "examples_widget" ("name")'
        )

        plan = plan_convergence()
        items = plan.executable()
        drops = [item for item in items if isinstance(item.fix, DropIndexFix)]
        assert len(drops) == 1
        assert drops[0].blocks_sync is False

    def test_can_auto_fix_for_missing(self, db):
        """can_auto_fix returns True for missing indexes and constraints."""
        assert can_auto_fix(IndexDrift(kind=DriftKind.MISSING, table="t"))
        assert can_auto_fix(ConstraintDrift(kind=DriftKind.MISSING, table="t"))

    def test_can_auto_fix_false_for_changed_constraint(self):
        """can_auto_fix returns False for changed constraint definitions."""
        drift = ConstraintDrift(kind=DriftKind.CHANGED, table="t")
        assert not can_auto_fix(drift)


class TestConvergencePlan:
    def test_executable_includes_undeclared_drops(self, db):
        """Undeclared objects are included in executable items."""
        execute(
            'CREATE INDEX "examples_widget_extra_idx" ON "examples_widget" ("name")'
        )

        plan = plan_convergence()
        items = plan.executable()
        drops = [item for item in items if isinstance(item.fix, DropIndexFix)]
        assert len(drops) == 1

    def test_has_work_includes_undeclared(self, db):
        """has_work() counts undeclared drops."""
        execute(
            'CREATE INDEX "examples_widget_extra_idx" ON "examples_widget" ("name")'
        )

        plan = plan_convergence()
        assert plan.has_work()

    def test_has_work_counts_forward_fixes(self, db):
        """has_work() sees forward fixes."""
        original_indexes = list(Widget.model_options.indexes)
        Widget.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_widget_name_idx"),
        ]

        try:
            plan = plan_convergence()
            assert plan.has_work()
        finally:
            Widget.model_options.indexes = original_indexes

    def test_blocked_for_changed_constraint(self, db):
        """Changed constraint definition appears in plan.blocked."""
        original_constraints = list(Widget.model_options.constraints)
        check = CheckConstraint(
            check=Q(id__gte=1),
            name="examples_widget_id_nonneg",
        )
        Widget.model_options.constraints = [*original_constraints, check]
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_id_nonneg" CHECK ("id" >= 0)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                plan = plan_model_convergence(conn, cursor, Widget)

            assert len(plan.blocked) == 1
            assert isinstance(plan.blocked[0].drift, ConstraintDrift)
            assert plan.blocked[0].drift.kind == DriftKind.CHANGED
            assert plan.blocked[0].fix is None
            assert plan.blocked[0].guidance is not None
        finally:
            Widget.model_options.constraints = original_constraints


class TestExecutePlan:
    def test_collects_results(self, isolated_db):
        """execute_plan() collects SQL from successful items."""
        execute('CREATE INDEX "examples_widget_temp_idx" ON "examples_widget" ("name")')
        fix = DropIndexFix(table="examples_widget", name="examples_widget_temp_idx")
        drift = IndexDrift(
            kind=DriftKind.UNDECLARED,
            table="examples_widget",
            name="examples_widget_temp_idx",
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=False)

        result = execute_plan([item])

        assert result.applied == 1
        assert result.failed == 0
        assert result.ok
        assert len(result.results) == 1
        assert result.results[0].ok
        assert "examples_widget_temp_idx" in (result.results[0].sql or "")

    def test_handles_failure(self, isolated_db):
        """execute_plan() captures errors without raising."""
        fix = DropConstraintFix(table="examples_widget", name="nonexistent")
        drift = ConstraintDrift(
            kind=DriftKind.UNDECLARED, table="examples_widget", name="nonexistent"
        )
        item = PlanItem(drift=drift, fix=fix)

        result = execute_plan([item])

        assert result.applied == 0
        assert result.failed == 1
        assert not result.ok
        assert result.results[0].error is not None

    def test_continues_after_failure(self, isolated_db):
        """A failed item doesn't block subsequent items."""
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_real_check" CHECK ("id" >= 0)'
        )

        items = [
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_widget",
                    name="nonexistent",
                ),
                fix=DropConstraintFix(table="examples_widget", name="nonexistent"),
            ),
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_widget",
                    name="examples_widget_real_check",
                ),
                fix=DropConstraintFix(
                    table="examples_widget", name="examples_widget_real_check"
                ),
            ),
        ]

        result = execute_plan(items)

        assert result.applied == 1
        assert result.failed == 1
        assert not constraint_exists("examples_widget", "examples_widget_real_check")

    def test_summary(self, isolated_db):
        """ConvergenceResult.summary formats correctly."""
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_real_check" CHECK ("id" >= 0)'
        )

        items = [
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_widget",
                    name="nonexistent",
                ),
                fix=DropConstraintFix(table="examples_widget", name="nonexistent"),
            ),
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_widget",
                    name="examples_widget_real_check",
                ),
                fix=DropConstraintFix(
                    table="examples_widget", name="examples_widget_real_check"
                ),
            ),
        ]

        result = execute_plan(items)

        assert result.summary == "1 applied, 1 failed."

    def test_result_item_reference(self, isolated_db):
        """FixResult.item references the PlanItem."""
        execute('CREATE INDEX "examples_widget_temp_idx" ON "examples_widget" ("name")')
        fix = DropIndexFix(table="examples_widget", name="examples_widget_temp_idx")
        drift = IndexDrift(
            kind=DriftKind.UNDECLARED,
            table="examples_widget",
            name="examples_widget_temp_idx",
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=False)

        result = execute_plan([item])

        assert result.results[0].item is item


class TestSyncPolicy:
    """Tests for blocks_sync and ok_for_sync semantics."""

    def test_blocking_failure_fails_sync(self, isolated_db):
        """A failed constraint fix (blocks_sync=True) makes ok_for_sync False."""
        fix = DropConstraintFix(table="examples_widget", name="nonexistent")
        drift = ConstraintDrift(
            kind=DriftKind.UNDECLARED, table="examples_widget", name="nonexistent"
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=True)

        result = execute_plan([item])

        assert not result.ok
        assert not result.ok_for_sync
        assert len(result.blocking_failures) == 1
        assert result.non_blocking_failures == []

    def test_non_blocking_failure_passes_sync(self, isolated_db):
        """A failed index fix (blocks_sync=False) keeps ok_for_sync True."""
        fix = CreateIndexFix(
            table="examples_widget",
            index=Index(fields=["name"], name="examples_widget_will_fail_idx"),
            model=Widget,
        )
        drift = IndexDrift(
            kind=DriftKind.MISSING,
            table="examples_widget",
            index=fix.index,
            model=Widget,
        )
        item = PlanItem(drift=drift, fix=fix, blocks_sync=False)

        # Create it first so the CONCURRENTLY create will fail (duplicate)
        execute(
            'CREATE INDEX "examples_widget_will_fail_idx" ON "examples_widget" ("name")'
        )

        result = execute_plan([item])

        assert not result.ok
        assert result.ok_for_sync
        assert result.blocking_failures == []
        assert len(result.non_blocking_failures) == 1

    def test_mixed_failures(self, isolated_db):
        """Blocking + non-blocking failures: ok_for_sync reflects only blocking."""
        execute(
            'CREATE INDEX "examples_widget_will_fail_idx" ON "examples_widget" ("name")'
        )

        index = Index(fields=["name"], name="examples_widget_will_fail_idx")
        items = [
            # Non-blocking: will fail (duplicate index)
            PlanItem(
                drift=IndexDrift(
                    kind=DriftKind.MISSING,
                    table="examples_widget",
                    index=index,
                    model=Widget,
                ),
                fix=CreateIndexFix(table="examples_widget", index=index, model=Widget),
                blocks_sync=False,
            ),
            # Blocking: will fail (nonexistent constraint)
            PlanItem(
                drift=ConstraintDrift(
                    kind=DriftKind.UNDECLARED,
                    table="examples_widget",
                    name="nonexistent",
                ),
                fix=DropConstraintFix(table="examples_widget", name="nonexistent"),
                blocks_sync=True,
            ),
        ]

        result = execute_plan(items)

        assert not result.ok
        assert not result.ok_for_sync
        assert len(result.blocking_failures) == 1
        assert len(result.non_blocking_failures) == 1

    def test_all_success_passes_sync(self, isolated_db):
        """All items succeeding means ok_for_sync is True."""
        execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "examples_widget_temp" CHECK ("id" >= 0)'
        )
        fix = DropConstraintFix(table="examples_widget", name="examples_widget_temp")
        drift = ConstraintDrift(
            kind=DriftKind.UNDECLARED,
            table="examples_widget",
            name="examples_widget_temp",
        )
        item = PlanItem(drift=drift, fix=fix)

        result = execute_plan([item])

        assert result.ok
        assert result.ok_for_sync

    def test_empty_result_passes_sync(self):
        """No items executed means ok_for_sync is True."""
        result = execute_plan([])
        assert result.ok_for_sync
