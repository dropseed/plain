"""System tests for the `plain postgres diagnose` pipeline.

Covers the 80/20: every check runs cleanly against a real database, the
deterministic structural checks detect staged scenarios, and the CLI produces
valid JSON output that reflects live findings.

Scenario tests stage DDL inside the `db` fixture's transaction, so tables,
indexes, and catalog tweaks all roll back at teardown. Scratch objects use a
`_diag_` prefix so findings can be located regardless of any baseline state
in the shared test database.
"""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner

from plain.postgres import get_connection
from plain.postgres.cli.diagnose import diagnose as diagnose_cli
from plain.postgres.introspection import (
    CheckResult,
    build_table_owners,
    run_all_checks,
)
from plain.postgres.introspection.health.checks_structural import (
    check_duplicate_indexes,
    check_invalid_indexes,
    check_missing_fk_indexes,
    check_sequence_exhaustion,
)


def _execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


def _find_check(results: list[CheckResult], name: str) -> CheckResult:
    for r in results:
        if r["name"] == name:
            return r
    raise AssertionError(
        f"check {name!r} not found in results; got {[r['name'] for r in results]}"
    )


@pytest.mark.usefixtures("_unblock_cursor", "db")
class TestRunAllChecks:
    """Smoke: every check runs against the real test DB without erroring and
    returns a well-formed CheckResult. This is the cheap regression net —
    catches SQL typos, catalog-view drift, and packaging/import breakage
    across the health module split."""

    def test_all_checks_produce_wellformed_results(self) -> None:
        conn = get_connection()
        table_owners = build_table_owners()
        with conn.cursor() as cursor:
            results, context = run_all_checks(cursor, table_owners)

        assert results, "run_all_checks returned no results"

        # Known checks that must be present. Keeping this list here (rather
        # than reading it back from ALL_CHECKS) is the point — if a check is
        # renamed or removed, this test fails loudly.
        expected_names = {
            "invalid_indexes",
            "duplicate_indexes",
            "missing_fk_indexes",
            "sequence_exhaustion",
            "stats_freshness",
            "vacuum_health",
            "index_bloat",
            "unused_indexes",
            "missing_index_candidates",
            "long_running_connections",
            "blocking_queries",
        }
        got_names = {r["name"] for r in results}
        missing = expected_names - got_names
        assert not missing, f"checks missing from run_all_checks: {missing}"

        valid_statuses = {"ok", "warning", "critical", "skipped", "error"}
        valid_tiers = {"warning", "operational"}
        for r in results:
            assert r["status"] in valid_statuses, (
                f"{r['name']}: invalid status {r['status']!r}"
            )
            assert r["tier"] in valid_tiers, f"{r['name']}: invalid tier {r['tier']!r}"
            assert isinstance(r["items"], list)
            assert isinstance(r["summary"], str)
            assert isinstance(r["message"], str)
            # If any check errored, surface its message so the failure is
            # actionable without having to rerun with -v.
            assert r["status"] != "error", (
                f"{r['name']} returned status=error: {r['message']}"
            )

        assert isinstance(context, dict)


@pytest.mark.usefixtures("_unblock_cursor", "db")
class TestStructuralScenarios:
    """Stage a known problem, run the specific check, assert it fires with
    the right shape. Only covers the four deterministic structural checks —
    cumulative and snapshot checks are left to the smoke test above."""

    def test_duplicate_indexes_detected(self) -> None:
        _execute('CREATE TABLE "_diag_dup" ("id" serial PRIMARY KEY, "a" int, "b" int)')
        _execute('CREATE INDEX "_diag_dup_a_idx" ON "_diag_dup" ("a")')
        _execute('CREATE INDEX "_diag_dup_ab_idx" ON "_diag_dup" ("a", "b")')

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        assert result["name"] == "duplicate_indexes"
        assert result["status"] == "warning"
        assert result["tier"] == "warning"

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup"]
        assert len(flagged) == 1, (
            f"expected exactly one duplicate on _diag_dup, got {flagged}"
        )
        assert flagged[0]["name"] == "_diag_dup_a_idx"
        assert "_diag_dup_ab_idx" in flagged[0]["detail"]

    def test_duplicate_indexes_detected_against_expression_index(self) -> None:
        """A plain-column index is redundant with a longer index whose
        trailing columns are expressions (e.g. `(team, LOWER(email))`)."""
        _execute(
            'CREATE TABLE "_diag_dup_expr" ('
            '"id" serial PRIMARY KEY, "team_id" int, "email" text)'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_team_idx" ON "_diag_dup_expr" ("team_id")'
        )
        _execute(
            'CREATE UNIQUE INDEX "_diag_dup_expr_team_lower_email_uniq" '
            'ON "_diag_dup_expr" ("team_id", LOWER("email"))'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup_expr"]
        assert len(flagged) == 1, (
            f"expected one duplicate on _diag_dup_expr, got {flagged}"
        )
        assert flagged[0]["name"] == "_diag_dup_expr_team_idx"
        assert "_diag_dup_expr_team_lower_email_uniq" in flagged[0]["detail"]

    def test_duplicate_indexes_detected_when_shorter_is_expression(self) -> None:
        """A `(LOWER(email))` index is redundant with `(LOWER(email), team_id)`
        — the longer index's leading column satisfies any read on the shorter,
        and `pg_get_indexdef` per-column comparison catches the match."""
        _execute(
            'CREATE TABLE "_diag_dup_expr_short" ('
            '"id" serial PRIMARY KEY, "email" text, "team_id" int)'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_short_lower_idx" '
            'ON "_diag_dup_expr_short" (LOWER("email"))'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_short_lower_team_idx" '
            'ON "_diag_dup_expr_short" (LOWER("email"), "team_id")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup_expr_short"]
        assert len(flagged) == 1, (
            f"expected one duplicate on _diag_dup_expr_short, got {flagged}"
        )
        assert flagged[0]["name"] == "_diag_dup_expr_short_lower_idx"
        assert "_diag_dup_expr_short_lower_team_idx" in flagged[0]["detail"]

    def test_duplicate_indexes_not_flagged_for_same_length_expression_indexes(
        self,
    ) -> None:
        """Two single-column expression indexes with different expressions
        (`LOWER(email)` vs `UPPER(email)`) — neither qualifies as shorter
        under `len(defs_s) < len(defs_l)`, so no false positive."""
        _execute(
            'CREATE TABLE "_diag_dup_expr_eq" ("id" serial PRIMARY KEY, "email" text)'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_eq_lower_idx" '
            'ON "_diag_dup_expr_eq" (LOWER("email"))'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_eq_upper_idx" '
            'ON "_diag_dup_expr_eq" (UPPER("email"))'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup_expr_eq"]
        assert flagged == [], (
            f"expected no duplicates flagged for same-length expression indexes, got {flagged}"
        )

    def test_duplicate_indexes_detected_when_longer_expression_index_is_not_unique(
        self,
    ) -> None:
        """Uniqueness only matters for the shorter side (a unique short index
        serves a constraint purpose). The longer side's uniqueness is
        irrelevant — a redundant non-unique short index should still be
        flagged against a non-unique longer expression index."""
        _execute(
            'CREATE TABLE "_diag_dup_expr_nonuniq" ('
            '"id" serial PRIMARY KEY, "team_id" int, "email" text)'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_nonuniq_team_idx" '
            'ON "_diag_dup_expr_nonuniq" ("team_id")'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_nonuniq_team_lower_idx" '
            'ON "_diag_dup_expr_nonuniq" ("team_id", LOWER("email"))'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup_expr_nonuniq"]
        assert len(flagged) == 1, (
            f"expected one duplicate on _diag_dup_expr_nonuniq, got {flagged}"
        )
        assert flagged[0]["name"] == "_diag_dup_expr_nonuniq_team_idx"
        assert "_diag_dup_expr_nonuniq_team_lower_idx" in flagged[0]["detail"]

    def test_duplicate_indexes_not_flagged_across_access_methods(self) -> None:
        """A hash index and a btree index on the same column support different
        operators (hash: only `=`; btree: ordering, range, etc.). Per-column
        text is identical, so we must check `pg_am.amname` to avoid telling
        the user to drop a deliberately-chosen hash index."""
        _execute(
            'CREATE TABLE "_diag_dup_am" ('
            '"id" serial PRIMARY KEY, "team_id" int, "email" text)'
        )
        _execute(
            'CREATE INDEX "_diag_dup_am_team_hash_idx" '
            'ON "_diag_dup_am" USING hash ("team_id")'
        )
        _execute(
            'CREATE INDEX "_diag_dup_am_team_email_idx" '
            'ON "_diag_dup_am" USING btree ("team_id", LOWER("email"))'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup_am"]
        assert flagged == [], (
            f"expected no duplicates flagged across access methods, got {flagged}"
        )

    def test_duplicate_indexes_not_flagged_when_longer_starts_with_expression(
        self,
    ) -> None:
        """A column-only shorter index `(team_id)` is not a true prefix of a
        longer index that leads with an expression `(LOWER(email), team_id)`
        — Postgres can't satisfy `WHERE team_id = ?` from the longer index,
        and per-column text comparison correctly skips it."""
        _execute(
            'CREATE TABLE "_diag_dup_expr_lead" ('
            '"id" serial PRIMARY KEY, "email" text, "team_id" int)'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_lead_team_idx" '
            'ON "_diag_dup_expr_lead" ("team_id")'
        )
        _execute(
            'CREATE INDEX "_diag_dup_expr_lead_lower_team_idx" '
            'ON "_diag_dup_expr_lead" (LOWER("email"), "team_id")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_duplicate_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_dup_expr_lead"]
        assert flagged == [], (
            f"expected no duplicates flagged when longer leads with expression, got {flagged}"
        )

    def test_missing_fk_index_detected(self) -> None:
        _execute('CREATE TABLE "_diag_fk_parent" ("id" serial PRIMARY KEY)')
        _execute(
            'CREATE TABLE "_diag_fk_child" ('
            '"id" serial PRIMARY KEY, '
            '"parent_id" int REFERENCES "_diag_fk_parent"("id"))'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_missing_fk_indexes(cursor, {})

        assert result["name"] == "missing_fk_indexes"
        assert result["status"] == "warning"

        flagged = [i for i in result["items"] if i["table"] == "_diag_fk_child"]
        assert len(flagged) == 1, (
            f"expected one missing FK index on _diag_fk_child, got {flagged}"
        )
        assert flagged[0]["name"] == "_diag_fk_child.parent_id"
        assert "_diag_fk_parent" in flagged[0]["detail"]

    def test_missing_fk_index_not_detected_when_indexed(self) -> None:
        _execute('CREATE TABLE "_diag_fk_parent2" ("id" serial PRIMARY KEY)')
        _execute(
            'CREATE TABLE "_diag_fk_child2" ('
            '"id" serial PRIMARY KEY, '
            '"parent_id" int REFERENCES "_diag_fk_parent2"("id"))'
        )
        _execute(
            'CREATE INDEX "_diag_fk_child2_parent_id_idx" ON "_diag_fk_child2" ("parent_id")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_missing_fk_indexes(cursor, {})

        flagged = [i for i in result["items"] if i["table"] == "_diag_fk_child2"]
        assert flagged == [], f"indexed FK should not be flagged; got {flagged}"

    def test_sequence_exhaustion_critical_above_90pct(self) -> None:
        _execute('CREATE TABLE "_diag_seq" ("id" serial PRIMARY KEY, "n" int)')
        # int4 sequence max is 2^31-1 = 2147483647; push past 90% to trip critical.
        _execute('ALTER SEQUENCE "_diag_seq_id_seq" RESTART WITH 2000000000')
        # last_value is NULL until the sequence is actually advanced. nextval()
        # populates it and moves the counter forward into the danger zone.
        _execute("SELECT nextval('\"_diag_seq_id_seq\"')")

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_sequence_exhaustion(cursor, {})

        assert result["name"] == "sequence_exhaustion"
        assert result["status"] == "critical", (
            f"expected critical at >90% sequence usage, got {result['status']} "
            f"(summary={result['summary']!r})"
        )

        flagged = [i for i in result["items"] if i["table"] == "_diag_seq"]
        assert len(flagged) == 1
        assert flagged[0]["name"] == "_diag_seq.id"
        assert "bigint" in flagged[0]["suggestion"]

    def test_invalid_index_detected(self) -> None:
        _execute('CREATE TABLE "_diag_inv" ("id" serial PRIMARY KEY, "a" int)')
        _execute('CREATE INDEX "_diag_inv_a_idx" ON "_diag_inv" ("a")')
        # Simulate a failed CREATE INDEX CONCURRENTLY by flipping indisvalid
        # directly in the catalog. Requires superuser, which the test role has.
        _execute(
            "UPDATE pg_index SET indisvalid = false "
            "WHERE indexrelid = '\"_diag_inv_a_idx\"'::regclass"
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            result = check_invalid_indexes(cursor, {})

        assert result["name"] == "invalid_indexes"
        assert result["status"] == "warning"

        flagged = [i for i in result["items"] if i["name"] == "_diag_inv_a_idx"]
        assert len(flagged) == 1
        assert flagged[0]["table"] == "_diag_inv"


@pytest.mark.usefixtures("_unblock_cursor", "db")
class TestDiagnoseCLI:
    """End-to-end: the CLI renders real findings. Only the JSON path is
    asserted — human formatting is exercised by hand and not worth snapshot
    maintenance. `use_management_connection()` is a no-op when
    POSTGRES_MANAGEMENT_URL is unset (the test case), so CLI-side SQL sees
    the staged scenario inside the test transaction."""

    def test_json_output_includes_staged_finding(self) -> None:
        import json

        _execute('CREATE TABLE "_diag_cli" ("id" serial PRIMARY KEY, "a" int, "b" int)')
        _execute('CREATE INDEX "_diag_cli_a_idx" ON "_diag_cli" ("a")')
        _execute('CREATE INDEX "_diag_cli_ab_idx" ON "_diag_cli" ("a", "b")')

        runner = CliRunner()
        result = runner.invoke(diagnose_cli, ["--json"], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        payload: dict[str, Any] = json.loads(result.output)
        assert "checks" in payload
        assert "context" in payload

        dup_check = next(
            c for c in payload["checks"] if c["name"] == "duplicate_indexes"
        )
        assert dup_check["status"] == "warning"
        names = {i["name"] for i in dup_check["items"]}
        assert "_diag_cli_a_idx" in names, (
            f"staged duplicate missing from JSON output; got {names}"
        )
