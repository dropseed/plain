"""Tests for heartbeat-based LOST detection and Job.on_aborted hook."""

from __future__ import annotations

import datetime
import socket
import uuid
from concurrent.futures import Future

import pytest

from plain.exceptions import ValidationError
from plain.jobs import Job
from plain.jobs.models import (
    JobProcess,
    JobRequest,
    JobResult,
    JobResultStatuses,
    WorkerHeartbeat,
    rescue_stale_workers,
)
from plain.jobs.registry import jobs_registry, register_job
from plain.jobs.workers import Worker, future_finished_callback
from plain.utils import timezone

_aborted_calls: list[JobResult] = []


@register_job
class _RecordingJob(Job):
    """Records every on_aborted invocation in module-level state."""

    def run(self) -> None:
        pass

    def on_aborted(self, result: JobResult) -> None:
        _aborted_calls.append(result)


@register_job
class _RaisingAbortedJob(Job):
    """on_aborted always raises — used to verify the hook's exceptions are swallowed."""

    def run(self) -> None:
        pass

    def on_aborted(self, result: JobResult) -> None:
        raise RuntimeError("boom from on_aborted")


@register_job
class _PlainJob(Job):
    """Default Job — doesn't override on_aborted."""

    def run(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_aborted_calls() -> None:
    _aborted_calls.clear()


def _make_job_process(
    job_class: type[Job],
    *,
    worker_id: uuid.UUID,
) -> JobProcess:
    """Create a JobProcess directly, bypassing the JobRequest queue."""
    name = jobs_registry.get_job_class_name(job_class)
    return JobProcess.query.create(
        job_request_uuid=uuid.uuid4(),
        job_class=name,
        parameters={"args": [], "kwargs": {}},
        worker_id=worker_id,
    )


def _make_heartbeat(
    *, worker_id: uuid.UUID | None = None, age_seconds: float = 0.0
) -> WorkerHeartbeat:
    last = timezone.now() - datetime.timedelta(seconds=age_seconds)
    return WorkerHeartbeat.query.create(
        worker_id=worker_id or uuid.uuid4(),
        hostname=socket.gethostname(),
        pid=12345,
        queues=["default"],
        last_heartbeat_at=last,
    )


def test_rescue_stale_workers_rescues_jobs_from_dead_worker(db, settings) -> None:
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    dead_worker_id = uuid.uuid4()
    _make_heartbeat(worker_id=dead_worker_id, age_seconds=120)
    job_process = _make_job_process(_RecordingJob, worker_id=dead_worker_id)

    rescue_stale_workers()

    # JobProcess deleted, JobResult created with LOST.
    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()
    result = JobResult.query.get(job_process_uuid=job_process.uuid)
    assert result.status == JobResultStatuses.LOST

    # Heartbeat row claimed and deleted.
    assert not WorkerHeartbeat.query.filter(worker_id=dead_worker_id).exists()


def test_rescue_stale_workers_leaves_alive_workers_alone(db, settings) -> None:
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    alive_worker_id = uuid.uuid4()
    _make_heartbeat(worker_id=alive_worker_id, age_seconds=10)
    job_process = _make_job_process(_RecordingJob, worker_id=alive_worker_id)

    rescue_stale_workers()

    assert JobProcess.query.filter(uuid=job_process.uuid).exists()
    assert WorkerHeartbeat.query.filter(worker_id=alive_worker_id).exists()
    assert not JobResult.query.filter(job_process_uuid=job_process.uuid).exists()


def test_rescue_stale_workers_long_running_legitimate_job_is_safe(db, settings) -> None:
    """A long-running JobProcess whose worker is still heartbeating must not be marked LOST.

    This is the corruption mode the previous JOBS_TIMEOUT design produced.
    """
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    alive_worker_id = uuid.uuid4()
    _make_heartbeat(worker_id=alive_worker_id, age_seconds=5)

    # Simulate a JobProcess that has existed for a "long" time.
    job_process = _make_job_process(_RecordingJob, worker_id=alive_worker_id)
    JobProcess.query.filter(uuid=job_process.uuid).update(
        created_at=timezone.now() - datetime.timedelta(days=2)
    )

    rescue_stale_workers()

    # JobProcess survives because its worker is alive.
    assert JobProcess.query.filter(uuid=job_process.uuid).exists()


def test_rescue_finds_dead_workers_on_other_queues(db, settings) -> None:
    """A worker rescuing on its own queue must still claim dead workers on other queues.

    Otherwise multi-queue deployments strand jobs: rescuer A on queue 'alpha' would
    delete dead worker B's heartbeat without converting B's queue 'beta' jobs, and
    those JobProcesses would have no heartbeat row to match ever again.
    """
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    dead_worker_id = uuid.uuid4()
    WorkerHeartbeat.query.create(
        worker_id=dead_worker_id,
        hostname=socket.gethostname(),
        pid=12345,
        queues=["beta"],
        last_heartbeat_at=timezone.now() - datetime.timedelta(seconds=120),
    )
    name = jobs_registry.get_job_class_name(_RecordingJob)
    job_process = JobProcess.query.create(
        job_request_uuid=uuid.uuid4(),
        job_class=name,
        parameters={"args": [], "kwargs": {}},
        queue="beta",
        worker_id=dead_worker_id,
    )

    # Simulates Worker A (scoped to 'alpha') ticking rescue. The unfiltered
    # rescue_stale_workers call is what makes this work.
    rescue_stale_workers()

    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()
    assert (
        JobResult.query.get(job_process_uuid=job_process.uuid).status
        == JobResultStatuses.LOST
    )


def test_rescue_stale_workers_rolls_back_heartbeat_on_conversion_failure(
    db, settings, monkeypatch
) -> None:
    """If conversion fails mid-rescue, the heartbeat must NOT be deleted.

    Otherwise the dead worker's remaining JobProcesses would have no heartbeat
    to match on the next rescue tick — stranded forever.
    """
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    dead_worker_id = uuid.uuid4()
    _make_heartbeat(worker_id=dead_worker_id, age_seconds=120)
    job_process = _make_job_process(_RecordingJob, worker_id=dead_worker_id)

    # Force convert_to_result to blow up.
    def _explode(self, **_):
        raise RuntimeError("simulated DB error mid-rescue")

    monkeypatch.setattr(JobProcess, "convert_to_result", _explode)

    rescue_stale_workers()  # should not raise — exception logged per-worker

    # Heartbeat survived (claim rolled back), JobProcess survived → next tick can retry.
    assert WorkerHeartbeat.query.filter(worker_id=dead_worker_id).exists()
    assert JobProcess.query.filter(uuid=job_process.uuid).exists()


def test_rescue_stale_workers_returns_pending_hooks_after_commit(db, settings) -> None:
    """rescue_stale_workers commits the rescue and returns JobResults whose
    on_aborted should fire. The caller dispatches them so it can interleave
    heartbeat ticks (a slow hook batch could otherwise starve the heartbeat
    and trigger false-positive LOST from a peer).
    """
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    dead_worker_id = uuid.uuid4()
    _make_heartbeat(worker_id=dead_worker_id, age_seconds=120)
    _make_job_process(_RecordingJob, worker_id=dead_worker_id)

    pending = rescue_stale_workers()

    # Rescue committed: heartbeat gone, JobResult exists.
    assert not WorkerHeartbeat.query.filter(worker_id=dead_worker_id).exists()
    assert JobResult.query.filter(status=JobResultStatuses.LOST).count() == 1

    # Hook is queued, not dispatched.
    assert _aborted_calls == []
    assert len(pending) == 1
    assert pending[0].status == JobResultStatuses.LOST

    # Caller fires it.
    pending[0].dispatch_aborted_hook()
    assert _aborted_calls == [pending[0]]


def test_on_aborted_fires_for_lost(db) -> None:
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())

    job_process.convert_to_result(status=JobResultStatuses.LOST)

    assert len(_aborted_calls) == 1
    assert _aborted_calls[0].status == JobResultStatuses.LOST


def test_on_aborted_fires_for_cancelled(db) -> None:
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())

    job_process.convert_to_result(status=JobResultStatuses.CANCELLED)

    assert len(_aborted_calls) == 1
    assert _aborted_calls[0].status == JobResultStatuses.CANCELLED


def test_on_aborted_does_not_fire_for_successful(db) -> None:
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())

    job_process.convert_to_result(status=JobResultStatuses.SUCCESSFUL)

    assert _aborted_calls == []


def test_on_aborted_does_not_fire_for_errored(db) -> None:
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())

    job_process.convert_to_result(status=JobResultStatuses.ERRORED, error="oops")

    assert _aborted_calls == []


def test_on_aborted_default_no_op_does_not_break_conversion(db) -> None:
    """Jobs that don't override on_aborted still convert cleanly."""
    job_process = _make_job_process(_PlainJob, worker_id=uuid.uuid4())

    result = job_process.convert_to_result(status=JobResultStatuses.LOST)

    assert result.status == JobResultStatuses.LOST


def test_on_aborted_exception_does_not_block_result(db) -> None:
    """A raise inside on_aborted must not prevent the JobResult from being recorded."""
    job_process = _make_job_process(_RaisingAbortedJob, worker_id=uuid.uuid4())

    result = job_process.convert_to_result(status=JobResultStatuses.LOST)

    assert result.status == JobResultStatuses.LOST
    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()


def test_on_aborted_unregistered_job_class_is_skipped(db) -> None:
    """If the Job class can't be loaded (e.g., deleted from code), result is still recorded."""
    job_process = JobProcess.query.create(
        job_request_uuid=uuid.uuid4(),
        job_class="app.NonexistentJob",
        parameters={"args": [], "kwargs": {}},
        worker_id=uuid.uuid4(),
    )

    result = job_process.convert_to_result(status=JobResultStatuses.LOST)

    assert result.status == JobResultStatuses.LOST


def test_jobresult_unique_per_jobprocess(db) -> None:
    """A second JobResult for the same JobProcess must be rejected.

    Guards the rescue-vs-late-finish race: if our heartbeat goes stale during
    a DB outage, a peer rescuer creates JobResult(LOST) for our JobProcess.
    When our subprocess eventually finishes and calls convert_to_result on
    the now-deleted JobProcess, the second insert must hit the unique
    constraint instead of silently producing two divergent results.
    """
    job_process_uuid = uuid.uuid4()
    JobResult.query.create(
        job_process_uuid=job_process_uuid,
        job_request_uuid=uuid.uuid4(),
        job_class="x",
        status=JobResultStatuses.LOST,
    )
    with pytest.raises(ValidationError):
        JobResult.query.create(
            job_process_uuid=job_process_uuid,
            job_request_uuid=uuid.uuid4(),
            job_class="x",
            status=JobResultStatuses.SUCCESSFUL,
        )


def test_convert_to_job_process_stamps_worker_id(db) -> None:
    name = jobs_registry.get_job_class_name(_RecordingJob)
    request = JobRequest.query.create(
        job_class=name,
        parameters={"args": [], "kwargs": {}},
    )
    worker_id = uuid.uuid4()

    process = request.convert_to_job_process(worker_id=worker_id)

    assert process.worker_id == worker_id


@pytest.fixture
def worker():
    """A real Worker. The ProcessPoolExecutor is shut down after the test."""
    w = Worker(queues=["default"], max_processes=1)
    try:
        yield w
    finally:
        w.executor.shutdown(wait=False, cancel_futures=True)


def test_register_heartbeat_creates_row(db, worker: Worker) -> None:
    worker.register_heartbeat()

    row = WorkerHeartbeat.query.get(worker_id=worker.worker_id)
    assert row.queues == ["default"]
    assert row.pid > 0


def test_maybe_heartbeat_updates_timestamp(db, worker: Worker, settings) -> None:
    settings.JOBS_HEARTBEAT_INTERVAL = 0  # always tick

    worker.register_heartbeat()
    initial = WorkerHeartbeat.query.get(worker_id=worker.worker_id).last_heartbeat_at

    worker.maybe_heartbeat()

    bumped = WorkerHeartbeat.query.get(worker_id=worker.worker_id).last_heartbeat_at
    assert bumped >= initial


def test_maybe_heartbeat_recreates_missing_row(db, worker: Worker, settings) -> None:
    """If the row is missing (e.g., another rescuer claimed us), re-register."""
    settings.JOBS_HEARTBEAT_INTERVAL = 0

    worker.register_heartbeat()
    WorkerHeartbeat.query.filter(worker_id=worker.worker_id).delete()

    worker.maybe_heartbeat()

    assert WorkerHeartbeat.query.filter(worker_id=worker.worker_id).exists()


def test_deregister_heartbeat_deletes_row(db, worker: Worker) -> None:
    worker.register_heartbeat()
    assert WorkerHeartbeat.query.filter(worker_id=worker.worker_id).exists()

    worker.deregister_heartbeat()

    assert not WorkerHeartbeat.query.filter(worker_id=worker.worker_id).exists()


def test_run_loop_returns_connection_each_tick(
    db, worker: Worker, settings, monkeypatch
) -> None:
    """The worker loop returns its pooled connection at the start of every
    tick. Holding one connection for the worker's whole life would let a
    server-side close wedge the loop reusing a dead connection forever."""
    settings.JOBS_HEARTBEAT_INTERVAL = 0
    worker.register_heartbeat()
    worker._heartbeat_registered = True

    # The no-job branch sleeps a second per tick — skip the real wait.
    monkeypatch.setattr("plain.jobs.workers.time.sleep", lambda *a, **kw: None)

    ticks = 0

    def _stop_after_two() -> None:
        nonlocal ticks
        ticks += 1
        if ticks >= 2:
            worker._is_shutting_down = True

    monkeypatch.setattr(
        "plain.jobs.workers.return_database_connection", _stop_after_two
    )

    worker._run_loop()

    assert ticks == 2


def test_future_finished_callback_rescues_orphan_jobprocess(db) -> None:
    """If a future completes "successfully" but the JobProcess row survives
    (because process_job's outer except-Exception swallowed a framework error
    before convert_to_result ran), the orphan must be converted to ERRORED.

    Otherwise the row sits forever — the parent worker is still heartbeating,
    so rescue_stale_workers never sees it as orphaned.
    """
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())

    # Simulate "future completed without exception" with a real Future.
    fake_future: Future = Future()
    fake_future.set_result(None)

    future_finished_callback(str(job_process.uuid), fake_future)

    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()
    result = JobResult.query.get(job_process_uuid=job_process.uuid)
    assert result.status == JobResultStatuses.ERRORED


def test_future_finished_callback_marks_killed_mid_run_as_lost(db) -> None:
    """If the child process dies abruptly (OOM/segfault) while run() is in
    flight, the future raises BrokenProcessPool. started_at was already set,
    so we treat it as LOST and fire on_aborted — user code may have set up
    state it expected to tear down.
    """
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())
    # Simulate the child having entered run() before being killed.
    job_process.started_at = timezone.now()
    job_process.update(fields=["started_at"])

    fake_future: Future = Future()
    fake_future.set_exception(RuntimeError("BrokenProcessPool"))

    future_finished_callback(str(job_process.uuid), fake_future)

    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()
    result = JobResult.query.get(job_process_uuid=job_process.uuid)
    assert result.status == JobResultStatuses.LOST
    assert _aborted_calls == [result]


def test_dispatch_aborted_hooks_ticks_heartbeat_between_hooks(
    db, worker: Worker, settings
) -> None:
    """A slow batch of on_aborted hooks must not starve the worker's
    heartbeat. The dispatcher ticks maybe_heartbeat() between every hook so
    a peer's rescue tick can't false-positive this worker as stale.
    """
    settings.JOBS_HEARTBEAT_INTERVAL = 0  # tick on every call
    worker.register_heartbeat()

    # Build three real JobResults to dispatch.
    results = []
    for _ in range(3):
        jp = _make_job_process(_RecordingJob, worker_id=worker.worker_id)
        results.append(
            jp.convert_to_result(status=JobResultStatuses.LOST, fire_hook=False)
        )

    initial_at = WorkerHeartbeat.query.get(worker_id=worker.worker_id).last_heartbeat_at

    worker._dispatch_aborted_hooks(results)

    # All hooks fired.
    assert len(_aborted_calls) == 3
    # Heartbeat got refreshed during dispatch.
    bumped_at = WorkerHeartbeat.query.get(worker_id=worker.worker_id).last_heartbeat_at
    assert bumped_at > initial_at


def test_dispatch_aborted_hooks_continues_after_raising_hook(
    db, worker: Worker
) -> None:
    """If one hook raises, dispatch_aborted_hook swallows it and the next
    hook still fires. The dispatcher keeps going rather than aborting the
    batch."""
    raising_jp = _make_job_process(_RaisingAbortedJob, worker_id=worker.worker_id)
    raising_result = raising_jp.convert_to_result(
        status=JobResultStatuses.LOST, fire_hook=False
    )
    recording_jp = _make_job_process(_RecordingJob, worker_id=worker.worker_id)
    recording_result = recording_jp.convert_to_result(
        status=JobResultStatuses.LOST, fire_hook=False
    )

    worker._dispatch_aborted_hooks([raising_result, recording_result])

    # The recording hook ran even though the raising one failed.
    assert _aborted_calls == [recording_result]


def test_rescue_own_orphans_converts_stranded_row_to_lost(
    db, worker: Worker, settings
) -> None:
    """Self-rescue: a JobProcess stamped to this worker, older than the
    threshold, and not in our inflight set is stranded — convert to LOST.

    Path that creates this state: future_finished_callback raised in
    convert_to_result (DB blip, peer race), exception escaped into
    concurrent.futures, _discard_inflight cleared the future. The row is
    sitting in DB with no path back since our heartbeat is fresh.
    """
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    job_process = _make_job_process(_RecordingJob, worker_id=worker.worker_id)
    # Backdate so it's past the cutoff.
    job_process.created_at = timezone.now() - datetime.timedelta(seconds=120)
    job_process.update(fields=["created_at"])

    worker._rescue_own_orphans()

    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()
    result = JobResult.query.get(job_process_uuid=job_process.uuid)
    assert result.status == JobResultStatuses.LOST


def test_rescue_own_orphans_leaves_inflight_rows_alone(
    db, worker: Worker, settings
) -> None:
    """A row whose future is still in our inflight dict must not be touched,
    even if it's older than the threshold (long-running job)."""
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    job_process = _make_job_process(_RecordingJob, worker_id=worker.worker_id)
    job_process.created_at = timezone.now() - datetime.timedelta(seconds=120)
    job_process.update(fields=["created_at"])

    fake_future: Future = Future()
    worker._inflight_futures[fake_future] = str(job_process.uuid)

    worker._rescue_own_orphans()

    assert JobProcess.query.filter(uuid=job_process.uuid).exists()


def test_rescue_own_orphans_respects_age_threshold(
    db, worker: Worker, settings
) -> None:
    """A freshly-claimed row not yet in the inflight dict (microsecond window
    between convert_to_job_process and the dict insert) must NOT be flagged
    as stranded — the threshold is exactly to protect this race."""
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    # Fresh row, default created_at = now.
    job_process = _make_job_process(_RecordingJob, worker_id=worker.worker_id)
    # Not in inflight set (simulating the moment between create and add).
    assert worker._inflight_futures == {}

    worker._rescue_own_orphans()

    # Still here — too young to be considered stranded.
    assert JobProcess.query.filter(uuid=job_process.uuid).exists()


def test_rescue_own_orphans_ignores_other_workers_rows(
    db, worker: Worker, settings
) -> None:
    """Self-rescue is per-worker. Rows owned by other workers are off-limits
    here — rescue_stale_workers handles those via heartbeat."""
    settings.JOBS_HEARTBEAT_TIMEOUT = 60

    other_worker_id = uuid.uuid4()
    other_job = _make_job_process(_RecordingJob, worker_id=other_worker_id)
    other_job.created_at = timezone.now() - datetime.timedelta(seconds=120)
    other_job.update(fields=["created_at"])

    worker._rescue_own_orphans()

    assert JobProcess.query.filter(uuid=other_job.uuid).exists()


def test_future_finished_callback_marks_unstarted_failure_as_errored(db) -> None:
    """If the future raises before run() ever started (e.g. process_job
    couldn't import the job class), started_at is unset. There's no in-flight
    user state to clean up, so ERRORED is correct and on_aborted does NOT fire.
    """
    job_process = _make_job_process(_RecordingJob, worker_id=uuid.uuid4())
    assert job_process.started_at is None

    fake_future: Future = Future()
    fake_future.set_exception(ImportError("module 'fake' not found"))

    future_finished_callback(str(job_process.uuid), fake_future)

    assert not JobProcess.query.filter(uuid=job_process.uuid).exists()
    result = JobResult.query.get(job_process_uuid=job_process.uuid)
    assert result.status == JobResultStatuses.ERRORED
    assert _aborted_calls == []


def test_deregister_keeps_heartbeat_when_jobprocess_still_stamped(
    db, worker: Worker
) -> None:
    """If JobProcess rows still reference us at shutdown, leave the heartbeat
    alone so rescue can pick them up. Deleting it would strand them.
    """
    worker.register_heartbeat()
    # Simulate an orphan JobProcess row (e.g., bookkeeping error during drain).
    name = jobs_registry.get_job_class_name(_RecordingJob)
    JobProcess.query.create(
        job_request_uuid=uuid.uuid4(),
        job_class=name,
        parameters={"args": [], "kwargs": {}},
        worker_id=worker.worker_id,
    )

    worker.deregister_heartbeat()

    # Heartbeat survived — rescue will eventually claim it as the worker dies.
    assert WorkerHeartbeat.query.filter(worker_id=worker.worker_id).exists()


def test_register_heartbeat_failure_leaves_unregistered(
    db, worker: Worker, monkeypatch
) -> None:
    """If the initial heartbeat insert fails, _heartbeat_registered stays False.

    The run loop checks this flag before claiming work — without it, an
    unregistered worker would stamp JobProcesses with a worker_id that has no
    heartbeat row to ever match, stranding them forever.
    """

    def _explode(self):
        raise RuntimeError("simulated DB error during heartbeat insert")

    monkeypatch.setattr(Worker, "_create_heartbeat_row", _explode)

    worker.register_heartbeat()

    assert worker._heartbeat_registered is False


def test_maybe_heartbeat_recovers_after_failed_registration(
    db, worker: Worker, settings
) -> None:
    """Once the DB recovers, maybe_heartbeat flips _heartbeat_registered to True."""
    settings.JOBS_HEARTBEAT_INTERVAL = 0
    # Simulate the post-failed-registration state.
    worker._heartbeat_registered = False

    worker.maybe_heartbeat()

    assert worker._heartbeat_registered is True
    assert WorkerHeartbeat.query.filter(worker_id=worker.worker_id).exists()


def test_maybe_heartbeat_clears_registered_flag_on_refresh_failure(
    db, worker: Worker, settings, monkeypatch
) -> None:
    """If refresh raises (row gone + recreate fails), the run loop must stop
    claiming work. Otherwise we'd keep stamping JobProcesses with a worker_id
    that has no heartbeat — stranding them if we die.
    """
    settings.JOBS_HEARTBEAT_INTERVAL = 0
    worker.register_heartbeat()
    assert worker._heartbeat_registered is True

    # Row gone + create raises = refresh raises.
    WorkerHeartbeat.query.filter(worker_id=worker.worker_id).delete()

    def _explode(self):
        raise RuntimeError("simulated DB error during recreate")

    monkeypatch.setattr(Worker, "_create_heartbeat_row", _explode)

    worker.maybe_heartbeat()

    assert worker._heartbeat_registered is False
