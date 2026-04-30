"""Convergence-side assertions for the ``POSTGRES_CONVERGENCE_*`` timeouts.

Two layers:

1. The ``_convergence_prelude`` builder emits the right SET LOCAL statements
   for the (blocking, local) combinations.
2. Each Fix subclass routes through ``_execute_and_commit`` /
   ``_execute_autocommit`` with the correct ``blocking`` flag (spy-based
   unit test — does not require a real DB connection).
3. One real-PG integration test: holding ACCESS EXCLUSIVE on a table via a
   second connection and asserting ``LockNotAvailable`` is raised fast.
"""

from __future__ import annotations

import threading
import time

import psycopg
import psycopg.errors
import pytest
from app.examples.models.indexes import IndexExample
from app.examples.models.relationships import Widget

from plain.postgres import Index, Q, get_connection
from plain.postgres.constraints import CheckConstraint, UniqueConstraint
from plain.postgres.convergence import fixes
from plain.postgres.convergence.fixes import (
    AddConstraintFix,
    AddForeignKeyFix,
    CreateIndexFix,
    DropColumnDefaultFix,
    DropConstraintFix,
    DropIndexFix,
    DropNotNullFix,
    RebuildIndexFix,
    RenameConstraintFix,
    RenameIndexFix,
    ReplaceForeignKeyFix,
    SetColumnDefaultFix,
    SetNotNullFix,
    ValidateConstraintFix,
    _convergence_prelude,
)
from plain.postgres.dialect import build_timeout_set_clauses
from plain.postgres.sources import build_connection_params
from plain.runtime import settings as plain_settings

# ---- Prelude builder ------------------------------------------------------


def test_prelude_blocking_local_emits_both_timeouts():
    prelude = _convergence_prelude(blocking=True, local=True)
    assert prelude == (
        "SET LOCAL lock_timeout = '3s'; SET LOCAL statement_timeout = '3s'; "
    )


def test_prelude_nonblocking_local_emits_lock_timeout_only():
    prelude = _convergence_prelude(blocking=False, local=True)
    assert prelude == "SET LOCAL lock_timeout = '3s'; "


def test_prelude_blocking_session_uses_plain_set():
    prelude = _convergence_prelude(blocking=True, local=False)
    assert prelude == "SET lock_timeout = '3s'; SET statement_timeout = '3s'; "


def test_prelude_nonblocking_session_uses_plain_set():
    prelude = _convergence_prelude(blocking=False, local=False)
    assert prelude == "SET lock_timeout = '3s'; "


def test_build_timeout_set_clauses_rejects_malformed_values():
    """Validation guards against typos in settings that would otherwise
    produce malformed SQL at runtime (e.g. a stray single-quote escaping
    the string literal). Unitless integers are also rejected so `"1"` can't
    silently become 1ms."""
    with pytest.raises(ValueError, match="Invalid Postgres interval"):
        build_timeout_set_clauses(
            lock_timeout="3s'; DROP TABLE users --", statement_timeout=None
        )
    with pytest.raises(ValueError, match="Invalid Postgres interval"):
        build_timeout_set_clauses(lock_timeout="3s", statement_timeout="not a duration")
    with pytest.raises(ValueError, match="Invalid Postgres interval"):
        build_timeout_set_clauses(lock_timeout="", statement_timeout=None)
    with pytest.raises(ValueError, match="Invalid Postgres interval"):
        # Bare integer: Postgres would interpret as ms — but a typo shouldn't
        # silently mean "1 millisecond".
        build_timeout_set_clauses(lock_timeout="100", statement_timeout=None)


def test_build_timeout_set_clauses_accepts_valid_intervals():
    """Common Postgres interval shapes must pass validation — including
    fractional values and mixed case, matching what Postgres accepts."""
    build_timeout_set_clauses(lock_timeout="3s", statement_timeout="500ms")
    build_timeout_set_clauses(lock_timeout="1min", statement_timeout="1h")
    build_timeout_set_clauses(lock_timeout="1 s", statement_timeout=None)  # space ok
    build_timeout_set_clauses(lock_timeout="1.5s", statement_timeout="0.5min")
    build_timeout_set_clauses(lock_timeout="3S", statement_timeout="500MS")


def test_prelude_values_propagate_from_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plain_settings, "POSTGRES_CONVERGENCE_LOCK_TIMEOUT", "250ms")
    monkeypatch.setattr(plain_settings, "POSTGRES_CONVERGENCE_STATEMENT_TIMEOUT", "7s")
    prelude = _convergence_prelude(blocking=True, local=True)
    assert "lock_timeout = '250ms'" in prelude
    assert "statement_timeout = '7s'" in prelude


# ---- Per-Fix routing (spy-based) -----------------------------------------


class _Spy:
    """Capture calls to the convergence helpers."""

    def __init__(self) -> None:
        self.commit_calls: list[tuple[str | list[str], bool]] = []
        self.autocommit_calls: list[str] = []

    def execute_and_commit(self, sql, *, blocking: bool = True) -> None:
        self.commit_calls.append((sql, blocking))

    def execute_autocommit(self, sql) -> None:
        self.autocommit_calls.append(sql)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    s = _Spy()
    monkeypatch.setattr(fixes, "_execute_and_commit", s.execute_and_commit)
    monkeypatch.setattr(fixes, "_execute_autocommit", s.execute_autocommit)
    return s


def test_rebuild_index_fix_uses_autocommit_only(spy: _Spy):
    fix = RebuildIndexFix(
        table="examples_indexexample",
        index=Index(fields=["name"], name="tmp_idx"),
        model=IndexExample,
    )
    fix.apply()
    assert spy.commit_calls == []
    assert len(spy.autocommit_calls) == 2  # DROP + CREATE


def test_create_index_fix_uses_autocommit(spy: _Spy):
    fix = CreateIndexFix(
        table="examples_indexexample",
        index=Index(fields=["name"], name="tmp_idx"),
        model=IndexExample,
    )
    fix.apply()
    assert spy.commit_calls == []
    assert len(spy.autocommit_calls) == 1


def test_rename_index_fix_is_blocking(spy: _Spy):
    RenameIndexFix(table="t", old_name="old_idx", new_name="new_idx").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_add_constraint_unique_mixes_autocommit_and_blocking_commit(spy: _Spy):
    """Unique constraint: CONCURRENTLY index then blocking ADD CONSTRAINT USING INDEX."""
    uc = UniqueConstraint(fields=["name", "size"], name="unique_widget_name_size")
    fix = AddConstraintFix(table="examples_widget", constraint=uc, model=Widget)
    fix.apply()
    # 1 autocommit (CREATE UNIQUE INDEX CONCURRENTLY)
    assert len(spy.autocommit_calls) == 1
    # 1 blocking commit (ALTER TABLE ... ADD CONSTRAINT ... USING INDEX)
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_add_constraint_check_blocking_add_then_nonblocking_validate(spy: _Spy):
    cc = CheckConstraint(check=Q(id__gte=0), name="check_widget_id")
    fix = AddConstraintFix(table="examples_widget", constraint=cc, model=Widget)
    fix.apply()
    assert spy.autocommit_calls == []
    assert len(spy.commit_calls) == 2
    # Step 1: ADD CONSTRAINT ... NOT VALID — blocking
    assert spy.commit_calls[0][1] is True
    # Step 2: VALIDATE CONSTRAINT — non-blocking
    assert spy.commit_calls[1][1] is False


def test_add_foreign_key_fix_blocking_add_then_nonblocking_validate(spy: _Spy):
    fix = AddForeignKeyFix(
        table="examples_widgettag",
        constraint_name="fk_x",
        column="widget_id",
        target_table="examples_widget",
        target_column="id",
    )
    fix.apply()
    assert len(spy.commit_calls) == 2
    # Step 1: ADD CONSTRAINT ... NOT VALID — blocking
    assert spy.commit_calls[0][1] is True
    # Step 2: VALIDATE CONSTRAINT — non-blocking
    assert spy.commit_calls[1][1] is False


def test_replace_foreign_key_fix_blocking_replace_then_nonblocking_validate(
    spy: _Spy,
):
    fix = ReplaceForeignKeyFix(
        table="examples_widgettag",
        constraint_name="fk_x",
        column="widget_id",
        target_table="examples_widget",
        target_column="id",
        on_delete_clause=" ON DELETE SET NULL",
    )
    fix.apply()
    assert len(spy.commit_calls) == 2
    assert spy.commit_calls[0][1] is True  # DROP+ADD
    assert spy.commit_calls[1][1] is False  # VALIDATE


def test_set_not_null_fix_tier_sequence(spy: _Spy):
    """SetNotNullFix: cleanup(ddl), ADD CHECK(ddl), VALIDATE(nonblocking),
    SET NOT NULL + DROP CONSTRAINT (ddl, list[str])."""
    fix = SetNotNullFix(table="examples_widget", column="name")
    fix.apply()
    assert len(spy.commit_calls) == 4
    assert spy.commit_calls[0][1] is True  # cleanup DROP CONSTRAINT IF EXISTS
    assert spy.commit_calls[1][1] is True  # ADD CHECK NOT VALID
    assert spy.commit_calls[2][1] is False  # VALIDATE CONSTRAINT
    # Step 4: combined SET NOT NULL + DROP temp check as a list
    combined_sql, blocking = spy.commit_calls[3]
    assert isinstance(combined_sql, list)
    assert len(combined_sql) == 2
    assert blocking is True


def test_drop_not_null_fix_blocking(spy: _Spy):
    DropNotNullFix(table="t", column="c").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_set_column_default_fix_blocking(spy: _Spy):
    SetColumnDefaultFix(table="t", column="c", default_sql="'x'").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_drop_column_default_fix_blocking(spy: _Spy):
    DropColumnDefaultFix(table="t", column="c").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_rename_constraint_fix_blocking(spy: _Spy):
    RenameConstraintFix(table="t", old_name="a", new_name="b").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_validate_constraint_fix_nonblocking(spy: _Spy):
    ValidateConstraintFix(table="t", name="c").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is False


def test_drop_constraint_fix_blocking(spy: _Spy):
    DropConstraintFix(table="t", name="c").apply()
    assert len(spy.commit_calls) == 1
    assert spy.commit_calls[0][1] is True


def test_drop_index_fix_uses_autocommit(spy: _Spy):
    DropIndexFix(table="t", name="idx_x").apply()
    assert spy.commit_calls == []
    assert len(spy.autocommit_calls) == 1


def test_autocommit_path_validates_malformed_setting(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    """The CONCURRENTLY path must reject a malformed lock_timeout setting
    at validation time — not silently embed it in the SQL where it would
    either malform the statement or (with a stray quote) escape the literal.
    Regression test for the validation-bypass gap on the autocommit path.
    Uses `isolated_db` because `_execute_autocommit` rejects running inside
    the wrapping atomic block of the standard `db` fixture."""
    from plain.postgres.convergence.fixes import _execute_autocommit

    monkeypatch.setattr(
        plain_settings,
        "POSTGRES_CONVERGENCE_LOCK_TIMEOUT",
        "3s'; DROP TABLE users --",
    )
    with pytest.raises(ValueError, match="Invalid Postgres interval"):
        _execute_autocommit("SELECT 1")


# ---- Real-PG integration: lock_timeout fires ------------------------------


def test_convergence_fix_hits_lock_timeout(
    isolated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    """With a tiny lock_timeout, a convergence fix on a table held under
    ACCESS EXCLUSIVE by another connection raises LockNotAvailable fast —
    not an unbounded wait.

    Uses `isolated_db` (fresh DB, no wrapping atomic block) because
    `_execute_and_commit` runs a real `COMMIT`, which `db` forbids.
    """
    monkeypatch.setattr(plain_settings, "POSTGRES_CONVERGENCE_LOCK_TIMEOUT", "100ms")

    conn_params = build_connection_params(get_connection().settings_dict)
    release_lock = threading.Event()
    holder_ready = threading.Event()
    holder_error: list[Exception] = []

    def hold_exclusive_lock() -> None:
        try:
            with psycopg.connect(**conn_params) as holder:
                holder.autocommit = False
                with holder.cursor() as cur:
                    cur.execute(
                        'LOCK TABLE "examples_indexexample" IN ACCESS EXCLUSIVE MODE'
                    )
                    holder_ready.set()
                    release_lock.wait(timeout=10)
                holder.rollback()
        except Exception as e:
            holder_error.append(e)
            holder_ready.set()

    holder_thread = threading.Thread(target=hold_exclusive_lock)
    holder_thread.start()
    assert holder_ready.wait(timeout=5), "holder failed to acquire exclusive lock"
    assert not holder_error, f"holder thread error: {holder_error[0]}"

    try:
        start = time.perf_counter()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            # SetColumnDefaultFix takes ACCESS EXCLUSIVE on the table —
            # conflicts with the held lock, must time out via lock_timeout.
            SetColumnDefaultFix(
                table="examples_indexexample",
                column="name",
                default_sql="'timeout_test'",
            ).apply()
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"Expected fast timeout but blocked for {elapsed:.2f}s"
    finally:
        release_lock.set()
        holder_thread.join(timeout=5)
