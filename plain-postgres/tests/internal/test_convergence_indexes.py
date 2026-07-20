from __future__ import annotations

import pytest
from app.examples.models.indexes import IndexExample
from conftest_convergence import (
    create_invalid_index,
    execute,
    index_exists,
    index_is_valid,
)

from plain.postgres import Index, Q, get_connection
from plain.postgres.convergence import (
    ReadOnlyConnectionError,
    plan_model_convergence,
)
from plain.postgres.convergence.analysis import (
    DriftKind,
    IndexDrift,
    IndexModelDrift,
    IndexRenameDrift,
    IndexUndeclaredDrift,
    analyze_model,
)
from plain.postgres.convergence.corrections import (
    CreateIndexCorrection,
    DropIndexCorrection,
    RebuildIndexCorrection,
    RenameIndexCorrection,
)
from plain.postgres.db import read_only
from plain.postgres.functions.text import Upper


def _create_hash_index(name: str = "examples_indexexample_name_hash_idx") -> None:
    execute(f'CREATE INDEX "{name}" ON "examples_indexexample" USING hash ("name")')


class TestUnmanagedIndexTypes:
    def test_hash_index_not_flagged_as_undeclared(self, db):
        """A hash index is unmanaged — no drift, shown as informational."""
        _create_hash_index()

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, IndexExample)

        # No drift for the hash index
        assert not any(
            isinstance(d, IndexDrift)
            and getattr(d, "name", None) == "examples_indexexample_name_hash_idx"
            for d in analysis.drifts
        )

        # Appears in indexes with access_method set (informational)
        hash_idx = next(
            idx
            for idx in analysis.indexes
            if idx.name == "examples_indexexample_name_hash_idx"
        )
        assert hash_idx.access_method == "hash"
        assert hash_idx.issue is None
        assert hash_idx.drift is None

    def test_unmanaged_index_not_auto_dropped(self, db):
        """Convergence does not propose dropping unmanaged index types."""
        _create_hash_index()

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, IndexExample).executable()

        assert not any(
            isinstance(item.correction, DropIndexCorrection)
            and item.correction.name == "examples_indexexample_name_hash_idx"
            for item in items
        )

    def test_btree_extra_index_still_undeclared(self, db):
        """A btree index not in the model is still flagged as undeclared."""
        execute(
            'CREATE INDEX "examples_indexexample_extra_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, IndexExample)

        assert any(
            isinstance(d, IndexDrift) and d.kind == DriftKind.UNDECLARED
            for d in analysis.drifts
        )

    def test_unmanaged_index_not_counted_as_issue(self, db):
        """Unmanaged indexes don't count toward the issue total."""
        _create_hash_index()

        conn = get_connection()
        with conn.cursor() as cursor:
            analysis = analyze_model(conn, cursor, IndexExample)

        assert analysis.issue_count == 0

    def test_name_conflict_with_unmanaged_index(self, db):
        """A declared index whose name collides with a hash index is an error."""
        _create_hash_index("examples_indexexample_name_idx")

        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, IndexExample)

            conflict = next(
                idx
                for idx in analysis.indexes
                if idx.name == "examples_indexexample_name_idx" and idx.issue
            )
            assert conflict.issue is not None
            assert "name conflict" in conflict.issue
            assert "hash" in conflict.issue
            assert conflict.drift is None  # no auto-correction
        finally:
            IndexExample.model_options.indexes = original_indexes


class TestDescendingIndexNoDrift:
    """A model Index that declares a descending field (`-name`) must converge
    without drift. Regression: the DB's `col DESC` from pg_get_indexdef was
    being parsed as an opclass of `"desc"`, flagging every sync as changed."""

    def test_descending_index_has_no_drift_on_second_sync(self, db):
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["-name"], name="examples_indexexample_name_desc_idx"),
        ]

        try:
            # First create the index to match the model.
            execute(
                'CREATE INDEX "examples_indexexample_name_desc_idx" '
                'ON "examples_indexexample" ("name" DESC)'
            )

            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, IndexExample)

            matching = next(
                idx
                for idx in analysis.indexes
                if idx.name == "examples_indexexample_name_desc_idx"
            )
            assert matching.drift is None, f"unexpected drift: {matching.issue}"
            assert matching.issue is None
        finally:
            IndexExample.model_options.indexes = original_indexes


class TestDetectIndexFixes:
    def test_detects_missing_index(self, db):
        """Add an index to the model, detect it as missing."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            index_items = [
                item
                for item in items
                if isinstance(item.correction, CreateIndexCorrection)
            ]
            assert len(index_items) == 1
            assert isinstance(index_items[0].correction, CreateIndexCorrection)
            assert (
                index_items[0].correction.index.name == "examples_indexexample_name_idx"
            )
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_extra_index(self, db):
        """An index in the DB not declared on the model is auto-dropped."""
        execute(
            'CREATE INDEX "examples_indexexample_extra_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, IndexExample).executable()

        index_items = [
            item for item in items if isinstance(item.correction, DropIndexCorrection)
        ]
        assert len(index_items) == 1
        correction = index_items[0].correction
        assert isinstance(correction, DropIndexCorrection)
        assert correction.name == "examples_indexexample_extra_idx"

    def test_detects_invalid_index(self, isolated_db):
        """An INVALID index matching a model index produces a RebuildIndexCorrection."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_idx"),
        ]

        create_invalid_index(
            "examples_indexexample_name_idx",
            table="examples_indexexample",
            column="name",
        )

        try:
            assert index_exists("examples_indexexample_name_idx")
            assert not index_is_valid("examples_indexexample_name_idx")

            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            correction = rebuild_items[0].correction
            assert isinstance(correction, RebuildIndexCorrection)
            assert correction.index.name == "examples_indexexample_name_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_index_definition_changed(self, db):
        """An index with the same name but different columns produces a RebuildIndexCorrection."""
        original_indexes = list(IndexExample.model_options.indexes)
        # Model declares index on "name" field
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_idx"),
        ]

        # DB has index on "description" column instead
        execute(
            'CREATE INDEX "examples_indexexample_name_idx"'
            ' ON "examples_indexexample" ("description")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            correction = rebuild_items[0].correction
            assert isinstance(correction, RebuildIndexCorrection)
            assert correction.index.name == "examples_indexexample_name_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_index_sort_order_changed(self, db):
        """An index whose model declaration is DESC but the live index is
        ASC must be detected as drift. Round-tripping the model side through
        pg_get_indexdef preserves the sort modifier in the normalized text."""
        original_indexes = list(IndexExample.model_options.indexes)
        # Model declares DESC ordering on `name`.
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["-name"], name="examples_indexexample_name_idx"),
        ]
        # DB has ascending (default) — same column, different sort.
        execute(
            'CREATE INDEX "examples_indexexample_name_idx"'
            ' ON "examples_indexexample" ("name")'
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            assert isinstance(rebuild_items[0].correction, RebuildIndexCorrection)
            assert (
                rebuild_items[0].correction.index.name
                == "examples_indexexample_name_idx"
            )
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_partial_index_predicate_with_paren_in_literal(self, db):
        """Partial-index predicates whose string literal contains parentheses
        must still compare correctly. Round-tripping the model side through
        pg_get_indexdef means both sides come from the same deparser, so
        literal parens don't get confused with structural parens."""
        original_indexes = list(IndexExample.model_options.indexes)
        # Model: predicate has `)` inside the string literal.
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                condition=Q(description="a)b"),
                name="examples_indexexample_name_idx",
            ),
        ]
        # DB has a different literal that also contains `)`.
        execute(
            'CREATE INDEX "examples_indexexample_name_idx" '
            'ON "examples_indexexample" ("name") '
            "WHERE (description = 'a)c')"
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_partial_index_predicate_case_change(self, db):
        """Partial index predicate that differs only in literal case (e.g.
        `status='abc'` vs `status='ABC'`) must be detected as drift —
        pg_get_indexdef preserves literal contents verbatim, so the normalized
        tails differ."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                condition=Q(description="ABC"),
                name="examples_indexexample_name_idx",
            ),
        ]
        # DB has same column, but predicate uses lower-case literal.
        execute(
            'CREATE INDEX "examples_indexexample_name_idx" '
            'ON "examples_indexexample" ("name") '
            "WHERE (description = 'abc')"
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_index_include_changed(self, db):
        """An index with the same key columns but a different INCLUDE list
        is real drift — convergence must rebuild it. Earlier the
        normalization stripped INCLUDE entirely, so a missing or extra
        covered column went unreported."""
        original_indexes = list(IndexExample.model_options.indexes)
        # Model declares INCLUDE ("description") on the name index.
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                include=["description"],
                name="examples_indexexample_name_idx",
            ),
        ]

        # DB has the same key columns but no INCLUDE.
        execute(
            'CREATE INDEX "examples_indexexample_name_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            correction = rebuild_items[0].correction
            assert isinstance(correction, RebuildIndexCorrection)
            assert correction.index.name == "examples_indexexample_name_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_expression_index_definition_changed(self, db):
        """An expression index with the same name but different expression produces a RebuildIndexCorrection."""
        original_indexes = list(IndexExample.model_options.indexes)
        # Model declares UPPER(name)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(Upper("name"), name="examples_indexexample_name_expr_idx"),
        ]

        # DB has LOWER(name) under the same name
        execute(
            'CREATE INDEX "examples_indexexample_name_expr_idx"'
            ' ON "examples_indexexample" (LOWER("name"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            correction = rebuild_items[0].correction
            assert isinstance(correction, RebuildIndexCorrection)
            assert correction.index.name == "examples_indexexample_name_expr_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_expression_index_sort_order_change(self, db):
        """An expression index with the same expression but different sort
        direction must be detected as drift. Round-tripping the model side
        through pg_get_indexdef makes ASC/DESC visible in the normalized text
        (`UPPER(name)` vs `UPPER(name) DESC`), so a tail-string compare
        catches the drift even though indoption sits outside indexprs."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                Upper("name").desc(),
                name="examples_indexexample_name_expr_idx",
            ),
        ]
        # DB has the same expression but ASC (the default).
        execute(
            'CREATE INDEX "examples_indexexample_name_expr_idx"'
            ' ON "examples_indexexample" (UPPER("name"))'
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_mixed_expression_column_index_column_change(self, db):
        """An index combining an expression and a plain column must detect
        drift when only the plain column differs. Regression: an early
        version compared just the expression text from `pg_get_expr(indexprs)`
        (which omits plain-column entries) and missed the column swap."""
        from plain.postgres.functions.text import Lower

        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                Lower("name"),
                "description",
                name="examples_indexexample_mixed_idx",
            ),
        ]
        # DB has the same expression but the plain column is `name` instead
        # of `description`.
        execute(
            'CREATE INDEX "examples_indexexample_mixed_idx"'
            ' ON "examples_indexexample" (LOWER("name"), "name")'
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_expression_index(self, db):
        """An expression index with matching name and definition produces no issues."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(Upper("name"), name="examples_indexexample_name_expr_idx"),
        ]

        # DB has the same expression
        execute(
            'CREATE INDEX "examples_indexexample_name_expr_idx"'
            ' ON "examples_indexexample" (UPPER("name"))'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            assert items == []
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_index(self, db):
        """An index with matching name and matching columns produces no issues."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_idx"),
        ]

        # DB has index on "name" column — matches the model
        execute(
            'CREATE INDEX "examples_indexexample_name_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            assert items == []
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_opclass_change(self, db):
        """An index whose model declares an opclass (e.g. text_pattern_ops
        for prefix-match support) but whose live index uses the default
        opclass must be detected as drift. The normalized-tail compare puts
        the opclass inline in the `USING ...` body — a tail-string compare
        catches the drift directly."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                opclasses=["text_pattern_ops"],
                name="examples_indexexample_name_opclass_idx",
            ),
        ]
        # DB has the same column but the default opclass.
        execute(
            'CREATE INDEX "examples_indexexample_name_opclass_idx"'
            ' ON "examples_indexexample" ("name")'
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            correction = rebuild_items[0].correction
            assert isinstance(correction, RebuildIndexCorrection)
            assert correction.index.name == "examples_indexexample_name_opclass_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_opclass_index(self, db):
        """An index whose model and DB both declare the same non-default
        opclass must converge without drift. Symmetric pin to the
        opclass-change detection — pg_get_indexdef renders the opclass
        inline only when it differs from the column-type default, so both
        sides have to agree on opclass *and* on whether it's printed."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                opclasses=["text_pattern_ops"],
                name="examples_indexexample_name_opclass_idx",
            ),
        ]
        execute(
            'CREATE INDEX "examples_indexexample_name_opclass_idx"'
            ' ON "examples_indexexample" ("name" text_pattern_ops)'
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, IndexExample)
            matching = next(
                idx
                for idx in analysis.indexes
                if idx.name == "examples_indexexample_name_opclass_idx"
            )
            assert matching.drift is None, f"unexpected drift: {matching.issue}"
            assert matching.issue is None
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_partial_index_condition_changed(self, db):
        """A partial index with same name/columns but different WHERE produces a RebuildIndexCorrection."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                condition=Q(id__gt=100),
                name="examples_indexexample_name_partial_idx",
            ),
        ]

        # DB has partial index on same column but different condition
        execute(
            'CREATE INDEX "examples_indexexample_name_partial_idx"'
            ' ON "examples_indexexample" ("name") WHERE ("id" > 50)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            rebuild_items = [
                item
                for item in items
                if isinstance(item.correction, RebuildIndexCorrection)
            ]
            assert len(rebuild_items) == 1
            correction = rebuild_items[0].correction
            assert isinstance(correction, RebuildIndexCorrection)
            assert correction.index.name == "examples_indexexample_name_partial_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_partial_index(self, db):
        """A partial index with matching name, columns, and condition produces no issues."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                condition=Q(id__gt=100),
                name="examples_indexexample_name_partial_idx",
            ),
        ]

        # DB has the matching partial index
        execute(
            'CREATE INDEX "examples_indexexample_name_partial_idx"'
            ' ON "examples_indexexample" ("name") WHERE ("id" > 100)'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()

            assert items == []
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_no_false_rename_when_condition_differs(self, db):
        """Two indexes on same column but different conditions should not be detected as a rename."""
        original_indexes = list(IndexExample.model_options.indexes)
        # Model has a partial index with a condition
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(
                fields=["name"],
                condition=Q(id__gt=100),
                name="examples_indexexample_name_new_idx",
            ),
        ]

        # DB has an index on same column but no condition, under a different name
        execute(
            'CREATE INDEX "examples_indexexample_name_old_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, IndexExample)

            # Should NOT be a rename — definitions differ
            rename_drifts = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert len(rename_drifts) == 0

            # Should be a missing + undeclared instead
            missing = [d for d in analysis.drifts if isinstance(d, IndexModelDrift)]
            assert len(missing) == 1
            assert missing[0].index is not None
            assert missing[0].index.name == "examples_indexexample_name_new_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_no_false_index_rename_when_normalization_fails(self, db):
        """On a half-migrated DB the round-trip normalization can return
        the empty sentinel for every missing index. The rename detector
        must NOT bucket sentinel-failing indexes under "" — that would let
        unrelated missing/extra pairs collide and produce a falsely
        "renamed" report. Patches the normalizer to "" globally and
        asserts the missing/extra fall through to MISSING + UNDECLARED
        instead."""
        from unittest.mock import patch

        original_indexes = list(IndexExample.model_options.indexes)
        # Model declares one missing index.
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_new_idx"),
        ]
        # DB has a same-shape index under a different name — the structural
        # case that *would* be a rename if normalization worked.
        execute(
            'CREATE INDEX "examples_indexexample_name_old_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        try:
            with patch(
                "plain.postgres.convergence.analysis._normalize_index_def",
                return_value="",
            ):
                conn = get_connection()
                with conn.cursor() as cursor:
                    analysis = analyze_model(conn, cursor, IndexExample)

            # No false rename.
            renames = [
                d
                for d in analysis.drifts
                if isinstance(d, IndexDrift) and d.kind == DriftKind.RENAMED
            ]
            assert renames == []

            # Both sides reported separately instead.
            missing = [d for d in analysis.drifts if isinstance(d, IndexModelDrift)]
            assert len(missing) == 1
            assert missing[0].index is not None
            assert missing[0].index.name == "examples_indexexample_name_new_idx"

            undeclared = [
                d for d in analysis.drifts if isinstance(d, IndexUndeclaredDrift)
            ]
            assert len(undeclared) == 1
            assert undeclared[0].name == "examples_indexexample_name_old_idx"
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_index_drift_diagnostic_when_normalization_fails(self, db):
        """When the model and DB share an index name but
        `_normalize_index_def` returns "" (model SQL incompatible with
        live shape), `_compare_normalized_index` must still emit a CHANGED
        drift with the abridged "definition differs: DB has ..." message —
        no "model expects ..." half. Mirrors the constraint-side fallback
        diagnostic test."""
        from unittest.mock import patch

        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_normalize_idx"),
        ]
        # DB has the same index name with a different definition.
        execute(
            'CREATE INDEX "examples_indexexample_normalize_idx"'
            ' ON "examples_indexexample" ("description")'
        )

        try:
            with patch(
                "plain.postgres.convergence.analysis._normalize_index_def",
                return_value="",
            ):
                conn = get_connection()
                with conn.cursor() as cursor:
                    analysis = analyze_model(conn, cursor, IndexExample)

            status = next(
                idx
                for idx in analysis.indexes
                if idx.name == "examples_indexexample_normalize_idx"
            )
            assert isinstance(status.drift, IndexDrift)
            assert status.drift.kind == DriftKind.CHANGED
            assert status.issue is not None
            assert "DB has" in status.issue
            assert "USING" in status.issue
            assert "model expects" not in status.issue
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_detects_multiple_expression_index_renames_in_one_pass(self, db):
        """Multiple expression-based index renames in a single analyze pass
        each trigger their own `_normalize_index_def` round-trip — every
        call wraps the temp-table create/drop in `cursor.connection.transaction()`,
        which nests as a savepoint inside the outer analyze transaction. A
        broken nesting helper would either abort the cursor after the first
        round-trip or leak temp state and trip the second LIKE. Both renames
        must be detected from one analyze."""
        from plain.postgres.functions.text import Lower

        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(Upper("name"), name="examples_indexexample_upper_new"),
            Index(Lower("description"), name="examples_indexexample_lower_new"),
        ]
        # DB has matching expressions under the old names.
        execute(
            'CREATE INDEX "examples_indexexample_upper_old"'
            ' ON "examples_indexexample" (UPPER("name"))'
        )
        execute(
            'CREATE INDEX "examples_indexexample_lower_old"'
            ' ON "examples_indexexample" (LOWER("description"))'
        )
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, IndexExample)

            rename_drifts = [
                d for d in analysis.drifts if isinstance(d, IndexRenameDrift)
            ]
            assert len(rename_drifts) == 2
            assert {d.old_name for d in rename_drifts} == {
                "examples_indexexample_upper_old",
                "examples_indexexample_lower_old",
            }
            assert {d.new_name for d in rename_drifts} == {
                "examples_indexexample_upper_new",
                "examples_indexexample_lower_new",
            }
            # Neither should leak through as missing / undeclared.
            assert not any(
                isinstance(d, IndexDrift)
                and d.kind in (DriftKind.MISSING, DriftKind.UNDECLARED)
                for d in analysis.drifts
            )

            # Cursor must remain usable after the nested round-trips —
            # subsequent queries on the outer transaction must still work.
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
        finally:
            IndexExample.model_options.indexes = original_indexes


class TestApplyIndexFixes:
    def test_create_index(self, isolated_db):
        """CreateIndexCorrection creates an index using CONCURRENTLY."""
        original_indexes = list(IndexExample.model_options.indexes)
        index = Index(fields=["name"], name="examples_indexexample_name_idx")
        IndexExample.model_options.indexes = [*original_indexes, index]

        try:
            assert not index_exists("examples_indexexample_name_idx")

            correction = CreateIndexCorrection(
                table="examples_indexexample", index=index, model=IndexExample
            )
            sql = correction.apply()

            assert "CONCURRENTLY" in sql
            assert index_exists("examples_indexexample_name_idx")
        finally:
            IndexExample.model_options.indexes = original_indexes

    def test_drop_index(self, isolated_db):
        """DropIndexCorrection drops an index using CONCURRENTLY."""
        execute(
            'CREATE INDEX "examples_indexexample_temp_idx"'
            ' ON "examples_indexexample" ("name")'
        )
        assert index_exists("examples_indexexample_temp_idx")

        correction = DropIndexCorrection(
            table="examples_indexexample", name="examples_indexexample_temp_idx"
        )
        sql = correction.apply()

        assert "CONCURRENTLY" in sql
        assert not index_exists("examples_indexexample_temp_idx")

    def test_rebuild_invalid_index(self, isolated_db):
        """RebuildIndexCorrection drops an INVALID index and recreates it."""
        original_indexes = list(IndexExample.model_options.indexes)
        index = Index(fields=["name"], name="examples_indexexample_name_idx")
        IndexExample.model_options.indexes = [*original_indexes, index]

        create_invalid_index(
            "examples_indexexample_name_idx",
            table="examples_indexexample",
            column="name",
        )

        try:
            assert index_exists("examples_indexexample_name_idx")
            assert not index_is_valid("examples_indexexample_name_idx")

            correction = RebuildIndexCorrection(
                table="examples_indexexample",
                index=index,
                model=IndexExample,
            )
            sql = correction.apply()

            assert "DROP" in sql
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_indexexample_name_idx")
            assert index_is_valid("examples_indexexample_name_idx")
        finally:
            IndexExample.model_options.indexes = original_indexes


class TestApplyRenameIndex:
    def test_rename_index(self, isolated_db):
        """RenameIndexCorrection renames using ALTER INDEX ... RENAME TO."""
        execute(
            'CREATE INDEX "examples_indexexample_old_idx"'
            ' ON "examples_indexexample" ("name")'
        )
        assert index_exists("examples_indexexample_old_idx")

        correction = RenameIndexCorrection(
            table="examples_indexexample",
            old_name="examples_indexexample_old_idx",
            new_name="examples_indexexample_new_idx",
        )
        sql = correction.apply()

        assert "RENAME TO" in sql
        assert not index_exists("examples_indexexample_old_idx")
        assert index_exists("examples_indexexample_new_idx")

    def test_rename_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_new_idx"),
        ]
        execute(
            'CREATE INDEX "examples_indexexample_name_old_idx"'
            ' ON "examples_indexexample" ("name")'
        )

        try:
            conn = get_connection()

            # First pass: detect rename
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            assert len(items) == 1
            assert isinstance(items[0].correction, RenameIndexCorrection)

            items[0].correction.apply()
            assert index_exists("examples_indexexample_name_new_idx")
            assert not index_exists("examples_indexexample_name_old_idx")

            # Second pass: converged
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, IndexExample).executable()
            assert items == []
        finally:
            IndexExample.model_options.indexes = original_indexes


class TestReadOnlyConnection:
    """Convergence analysis normalizes the model side via temp-table DDL,
    so it can't run on a read-only / standby connection. Surface that as a
    clean domain error rather than a raw psycopg ReadOnlySqlTransaction."""

    def test_analyze_inside_read_only_raises_clean_error(self, isolated_db):
        # Same-name match → normalization runs → first DDL attempt under
        # read_only() raises ReadOnlySqlTransaction, which we translate.
        original_indexes = list(IndexExample.model_options.indexes)
        IndexExample.model_options.indexes = [
            *original_indexes,
            Index(fields=["name"], name="examples_indexexample_name_idx"),
        ]
        execute(
            'CREATE INDEX "examples_indexexample_name_idx"'
            ' ON "examples_indexexample" ("name")'
        )
        try:
            conn = get_connection()
            with read_only():
                with pytest.raises(
                    ReadOnlyConnectionError,
                    match="requires write access",
                ):
                    with conn.cursor() as cursor:
                        analyze_model(conn, cursor, IndexExample)
        finally:
            IndexExample.model_options.indexes = original_indexes
