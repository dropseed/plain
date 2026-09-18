"""The `migrations apply` command re-plans under the schema lock.

Pins the concurrent-deploy contract: two processes both plan the same pending
migration; the loser waits on the lock, then must re-plan and see the winner's
work instead of re-applying its stale plan (which would re-run DDL that
already exists and crash).
"""

from __future__ import annotations

from contextlib import contextmanager

from plain.postgres.cli.migrations import apply
from plain.postgres.db import get_connection
from plain.postgres.migrations.recorder import MigrationRecorder


def test_apply_replans_after_waiting_on_lock(db, monkeypatch, capsys):
    recorder = MigrationRecorder(get_connection())

    # Pick the latest applied migration of the test app and delete its record
    # (schema untouched) — `apply` now sees it as pending, exactly like the
    # loser of a two-process race that planned before the winner finished.
    applied = [name for app, name in recorder.applied_migrations() if app == "examples"]
    assert applied, "test app should have applied migrations"
    latest = max(applied)
    recorder.record_unapplied("examples", latest)

    # Simulate the winner: the moment the lock is acquired, the migration is
    # (already) applied. If `apply` executed its stale pre-lock plan instead
    # of re-planning, it would re-run this migration's DDL and crash.
    import plain.postgres.cli.migrations as migrations_cli

    real_lock = migrations_cli.cli_schema_lock

    @contextmanager
    def lock_with_racing_winner():
        with real_lock() as verify:
            recorder.record_applied("examples", latest)
            yield verify

    monkeypatch.setattr(migrations_cli, "cli_schema_lock", lock_with_racing_winner)

    apply.callback(
        package_label=None,
        migration_name=None,
        fake=False,
        plan=False,
        check_unapplied=False,
        no_input=True,
        atomic_batch=None,
        quiet=False,
    )

    out = capsys.readouterr().out
    assert "another process already applied them" in out
