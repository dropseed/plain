"""Statement pins for the worker's job-claim query.

Change detector: if the claim starts issuing different SQL — an extra round
trip, a lock on a different table, a dropped `SKIP LOCKED` — these fail and
you decide whether it should have.

Two things about how the statements are captured:

1. `_claim_job()` runs inside `suppress_db_tracing()`, so the `otel_spans`
   fixture sees nothing for it (pinned below). Statements are captured with
   `connection.execute_wrapper()` instead, which suppression doesn't touch.
2. The `db` fixture already holds the test inside a transaction, so the
   claim's `transaction.atomic()` opens a SAVEPOINT rather than a BEGIN.
   In production the claim's atomic block is the outermost one.
"""

from __future__ import annotations

import datetime
import threading

import pytest
from plain.jobs.models import JobRequest
from plain.jobs.workers import Worker
from plain.postgres.db import get_connection
from plain.utils import timezone

CLAIM_SELECT_TABLE = 'FROM "plainjobs_jobrequest"'
CLAIM_LOCK_CLAUSE = "FOR UPDATE SKIP LOCKED"


class StatementRecorder:
    """Records every statement executed on a connection, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, execute, sql, params, many, context):
        self.statements.append(" ".join(str(sql).split()))
        return execute(sql, params, many, context)


@pytest.fixture
def worker():
    w = Worker(queues=["default"], max_processes=1)
    try:
        yield w
    finally:
        w.executor.shutdown(wait=False, cancel_futures=True)


def test_claim_statements_when_a_job_is_pending(db, worker) -> None:
    now = timezone.now()
    JobRequest.query.create(
        job_class="app.Low", priority=1, queue="default", created_at=now
    )
    JobRequest.query.create(
        job_class="app.High", priority=10, queue="default", created_at=now
    )
    JobRequest.query.create(
        job_class="app.Mid",
        priority=5,
        queue="default",
        created_at=now - datetime.timedelta(minutes=1),
    )

    recorder = StatementRecorder()
    with get_connection().execute_wrapper(recorder):
        job_process = worker._claim_job()

    # Highest priority first — the claim's ordering decides which job runs.
    assert job_process is not None
    assert job_process.job_class == "app.High"

    statements = recorder.statements
    assert len(statements) == 7

    assert statements[0].startswith("SAVEPOINT ")

    assert statements[1].startswith("SELECT ")
    assert CLAIM_SELECT_TABLE in statements[1]
    assert (
        'ORDER BY "plainjobs_jobrequest"."priority" DESC, '
        '"plainjobs_jobrequest"."start_at" DESC, '
        '"plainjobs_jobrequest"."created_at" DESC' in statements[1]
    )
    assert statements[1].endswith(f"LIMIT 1 {CLAIM_LOCK_CLAUSE}")
    # No `OF` clause: the claim selects from one table, so the lock is
    # unambiguous and nothing else gets locked.
    assert " OF " not in statements[1]

    # convert_to_job_process() opens its own nested atomic block.
    assert statements[2].startswith("SAVEPOINT ")
    assert statements[3].startswith('INSERT INTO "plainjobs_jobprocess"')
    assert statements[4].startswith('DELETE FROM "plainjobs_jobrequest"')
    assert statements[5].startswith("RELEASE SAVEPOINT ")
    assert statements[6].startswith("RELEASE SAVEPOINT ")


def test_claim_statements_when_no_job_is_pending(db, worker) -> None:
    recorder = StatementRecorder()
    with get_connection().execute_wrapper(recorder):
        job_process = worker._claim_job()

    assert job_process is None

    statements = recorder.statements
    assert len(statements) == 3
    assert statements[0].startswith("SAVEPOINT ")
    assert statements[1].startswith("SELECT ")
    assert CLAIM_SELECT_TABLE in statements[1]
    assert statements[1].endswith(f"LIMIT 1 {CLAIM_LOCK_CLAUSE}")
    assert statements[2].startswith("RELEASE SAVEPOINT ")


def test_claim_emits_no_database_spans(db, worker, otel_spans) -> None:
    """The claim polls every ~1s outside any entry span, so the worker
    suppresses its tracing. An ordinary query emits a CLIENT span; the
    claim emits none."""
    JobRequest.query.create(job_class="app.Any", queue="default")
    assert otel_spans.get_finished_spans(), "ordinary queries do emit spans"

    otel_spans.clear()
    assert worker._claim_job() is not None

    assert otel_spans.get_finished_spans() == ()


def test_two_workers_racing_for_one_job(isolated_db) -> None:
    """`SKIP LOCKED` means the loser walks away empty-handed instead of
    blocking on the winner's lock.

    Needs `isolated_db`: the two threads open their own connections, so the
    pending job has to be committed, not sitting in a test transaction.
    """
    JobRequest.query.create(job_class="app.Only", queue="default")
    config = get_connection().settings_dict

    barrier = threading.Barrier(2)
    claimed: dict[int, object] = {}

    def claim(n: int) -> None:
        from plain.postgres.connection import DatabaseConnection
        from plain.postgres.db import _db_conn
        from plain.postgres.sources import DirectSource

        # A thread starts with an empty context, so give it its own
        # connection against the same test database.
        connection = DatabaseConnection(DirectSource(config))
        _db_conn.set(connection)

        w = Worker(queues=["default"], max_processes=1)
        try:
            barrier.wait(timeout=10)
            claimed[n] = w._claim_job()
        finally:
            w.executor.shutdown(wait=False, cancel_futures=True)
            connection.close()

    threads = [threading.Thread(target=claim, args=(n,)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a claim blocked — SKIP LOCKED was lost"

    winners = [n for n, job in claimed.items() if job is not None]
    losers = [n for n, job in claimed.items() if job is None]
    assert len(winners) == 1
    assert len(losers) == 1
