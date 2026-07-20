"""Ledger-based schedule evaluation: entries fire once per due slot, never
early, never retroactively, and stop firing the moment they leave
JOBS_SCHEDULE."""

from __future__ import annotations

import datetime
import uuid

import pytest

from plain.jobs import Job
from plain.jobs.models import (
    JobProcess,
    JobRequest,
    JobResult,
    JobResultStatuses,
    ScheduleState,
)
from plain.jobs.registry import jobs_registry, register_job
from plain.jobs.scheduling import (
    Schedule,
    ScheduledCommand,
    load_schedule,
    schedule_entry_key,
    scheduled_concurrency_key,
)
from plain.jobs.workers import Worker
from plain.utils import timezone

EVERY_MINUTE = Schedule.from_cron("* * * * *")


@register_job
class _TickJob(Job):
    def run(self) -> None:
        pass


@register_job
class _NeverEnqueueJob(Job):
    def run(self) -> None:
        pass

    def should_enqueue(self, concurrency_key: str) -> bool:
        return False


@register_job
class _RaisingEnqueueJob(Job):
    def run(self) -> None:
        pass

    def should_enqueue(self, concurrency_key: str) -> bool:
        raise RuntimeError("boom from should_enqueue")


@pytest.fixture
def make_worker():
    """Build Workers whose schedule pass runs immediately when called."""
    workers = []

    def _make(jobs_schedule=None) -> Worker:
        worker = Worker(
            queues=["default"],
            jobs_schedule=jobs_schedule or [],
            max_processes=1,
        )
        workers.append(worker)
        return worker

    yield _make

    for worker in workers:
        worker.executor.shutdown(wait=False, cancel_futures=True)


def _backdate_ledger(job: Job, schedule: Schedule, *, minutes: int) -> None:
    """Move an entry's ledger into the past so a slot is due right now."""
    ScheduleState.query.filter(schedule_key=schedule_entry_key(job, schedule)).update(
        last_enqueued_slot=timezone.now() - datetime.timedelta(minutes=minutes)
    )


def _run_schedule_pass(worker: Worker) -> None:
    """Run another schedule pass now, bypassing the schedule gate (the boot
    pass already consumed the immediate-evaluation baseline)."""
    worker._jobs_schedule_checked_at = 0.0
    worker.maybe_schedule_jobs()


def test_first_pass_initializes_ledger_without_firing(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])

    worker.maybe_schedule_jobs()

    state = ScheduleState.query.get(schedule_key=schedule_entry_key(job, EVERY_MINUTE))
    assert state.last_enqueued_slot <= timezone.now()
    assert not JobRequest.query.exists()


def test_due_slot_enqueues_ready_to_run_job(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker)

    job_request = JobRequest.query.get()
    assert job_request.job_class == jobs_registry.get_job_class_name(_TickJob)
    start_at = job_request.start_at
    assert start_at is not None
    assert start_at <= timezone.now()
    # start_at is the slot time itself (a minute boundary), not "now"
    assert start_at.second == 0
    assert start_at.microsecond == 0
    assert JobRequest.query.ready_to_run().exists()
    assert ":scheduled:" in job_request.concurrency_key


def test_slot_fires_once_across_worker_restarts(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker)

    # A restarted worker (fresh instance, same schedule) sees the advanced
    # ledger and enqueues nothing new.
    restarted = make_worker([(_TickJob(), EVERY_MINUTE)])
    restarted.maybe_schedule_jobs()

    assert JobRequest.query.count() == 1


def test_two_workers_fire_a_slot_once(db, make_worker):
    job_a, job_b = _TickJob(), _TickJob()
    worker_a = make_worker([(job_a, EVERY_MINUTE)])
    worker_b = make_worker([(job_b, EVERY_MINUTE)])
    worker_a.maybe_schedule_jobs()
    _backdate_ledger(job_a, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker_a)
    worker_b.maybe_schedule_jobs()

    assert JobRequest.query.count() == 1


def test_missed_slots_fire_latest_only(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=30)

    _run_schedule_pass(worker)

    job_request = JobRequest.query.get()
    # Only the most recent due slot fired, not the ~30 missed ones.
    start_at = job_request.start_at
    assert start_at is not None
    assert timezone.now() - start_at < datetime.timedelta(seconds=60)


def test_removed_entry_stops_firing_and_leaves_nothing_pending(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    # The entry was removed from JOBS_SCHEDULE (worker restarts without it)
    # before its slot came due. Nothing fires and nothing is pending — the
    # ledger row is inert bookkeeping.
    without_entry = make_worker([])
    without_entry.maybe_schedule_jobs()

    assert not JobRequest.query.exists()
    assert ScheduleState.query.count() == 1


def test_changed_schedule_starts_a_fresh_ledger(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    # The entry's timing changed: its identity changes, so the overdue slot
    # on the old ledger row never fires.
    hourly = Schedule.from_cron("0 * * * *")
    changed = make_worker([(_TickJob(), hourly)])
    changed.maybe_schedule_jobs()

    assert not JobRequest.query.exists()
    assert ScheduleState.query.count() == 2


def test_should_enqueue_false_still_consumes_the_slot(db, make_worker):
    job = _NeverEnqueueJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker)

    assert not JobRequest.query.exists()
    # The slot was evaluated and skipped — the ledger advanced so it isn't
    # re-offered every tick.
    state = ScheduleState.query.get(schedule_key=schedule_entry_key(job, EVERY_MINUTE))
    assert timezone.now() - state.last_enqueued_slot < datetime.timedelta(seconds=60)


def test_legacy_pre_enqueued_row_for_the_same_slot_dedupes(db, make_worker):
    """Upgrade path: a row pre-enqueued by the old scheduler for a slot must
    not double-fire when the ledger also reaches that slot."""
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    # Recreate what the old scheduler left behind: a pending row keyed to the
    # slot the ledger will fire next — for an every-minute schedule, the
    # latest due slot is the current minute boundary.
    due_slot = timezone.localtime().replace(second=0, microsecond=0)
    JobRequest.query.create(
        job_class=jobs_registry.get_job_class_name(_TickJob),
        parameters={"args": [], "kwargs": {}},
        queue="default",
        concurrency_key=scheduled_concurrency_key(job, due_slot),
        start_at=due_slot,
    )

    _run_schedule_pass(worker)

    assert JobRequest.query.count() == 1
    # The ledger still advanced past the deduped slot.
    state = ScheduleState.query.get(schedule_key=schedule_entry_key(job, EVERY_MINUTE))
    assert timezone.localtime(state.last_enqueued_slot) == due_slot


def test_completed_run_for_the_slot_blocks_reenqueue(db, make_worker):
    """Rolling-upgrade path: a slot whose legacy pre-enqueued row already ran
    to completion (only a JobResult remains) must not fire a second time."""
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    due_slot = timezone.localtime().replace(second=0, microsecond=0)
    JobResult.query.create(
        job_process_uuid=uuid.uuid4(),
        job_request_uuid=uuid.uuid4(),
        job_class=jobs_registry.get_job_class_name(_TickJob),
        status=JobResultStatuses.SUCCESSFUL,
        concurrency_key=scheduled_concurrency_key(job, due_slot),
    )

    _run_schedule_pass(worker)

    assert not JobRequest.query.exists()
    # The ledger still advanced — the slot is accounted for, just not re-run.
    state = ScheduleState.query.get(schedule_key=schedule_entry_key(job, EVERY_MINUTE))
    assert timezone.localtime(state.last_enqueued_slot) == due_slot


def test_duplicate_schedule_entries_are_rejected(db):
    with pytest.raises(ValueError, match="Duplicate JOBS_SCHEDULE entry"):
        load_schedule([(_TickJob(), "* * * * *"), (_TickJob(), "* * * * *")])


def test_long_command_schedules_and_fires(db, make_worker):
    """A long shell command must survive the whole path: ledger init (the
    unbounded schedule_key) AND the due-slot enqueue (the 255-char
    concurrency_key bound on JobRequest)."""
    command = "echo " + "x" * 300
    job = ScheduledCommand(command)
    worker = make_worker([(job, EVERY_MINUTE)])

    worker.maybe_schedule_jobs()
    assert ScheduleState.query.count() == 1

    _backdate_ledger(job, EVERY_MINUTE, minutes=2)
    _run_schedule_pass(worker)

    job_request = JobRequest.query.get()
    assert len(job_request.concurrency_key) <= 255


def test_broken_entry_does_not_starve_later_entries(db, make_worker):
    """A failing entry is contained per-entry: the entries after it still
    get evaluated in the same pass."""
    broken, healthy = _RaisingEnqueueJob(), _TickJob()
    worker = make_worker([(broken, EVERY_MINUTE), (healthy, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(broken, EVERY_MINUTE, minutes=2)
    _backdate_ledger(healthy, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker)

    job_request = JobRequest.query.get()
    assert job_request.job_class == jobs_registry.get_job_class_name(_TickJob)
    # The broken entry's claim rolled back with the failed enqueue, so its
    # slot stays available to retry next pass.
    broken_state = ScheduleState.query.get(
        schedule_key=schedule_entry_key(broken, EVERY_MINUTE)
    )
    assert timezone.now() - broken_state.last_enqueued_slot > datetime.timedelta(
        seconds=90
    )


def test_completed_older_slot_does_not_block_later_slots(db, make_worker):
    """The completed-run guard is slot-specific: a JobResult for an earlier
    slot must not suppress the current slot's fire."""
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=5)

    older_slot = (timezone.localtime() - datetime.timedelta(minutes=3)).replace(
        second=0, microsecond=0
    )
    JobResult.query.create(
        job_process_uuid=uuid.uuid4(),
        job_request_uuid=uuid.uuid4(),
        job_class=jobs_registry.get_job_class_name(_TickJob),
        status=JobResultStatuses.SUCCESSFUL,
        concurrency_key=scheduled_concurrency_key(job, older_slot),
    )

    _run_schedule_pass(worker)

    assert JobRequest.query.exists()


def test_stale_claim_enqueues_nothing(db, make_worker):
    """The optimistic claim: a pass working from a stale ledger read (another
    worker advanced the row mid-flight) must not enqueue."""
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    stale_slot = ScheduleState.query.get(
        schedule_key=schedule_entry_key(job, EVERY_MINUTE)
    ).last_enqueued_slot

    _run_schedule_pass(worker)  # advances the ledger and fires the slot
    assert JobRequest.query.count() == 1

    # Replay the claim with the stale pre-advance value.
    worker._schedule_entry(
        job,
        EVERY_MINUTE,
        schedule_entry_key(job, EVERY_MINUTE),
        stale_slot,
        timezone.localtime(),
    )

    assert JobRequest.query.count() == 1


def test_schedule_gate_blocks_back_to_back_passes(db, make_worker):
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker)
    assert JobRequest.query.count() == 1

    # Another due slot exists, but the gate was stamped at the start of the
    # pass above — an immediate second call does nothing.
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)
    worker.maybe_schedule_jobs()

    assert JobRequest.query.count() == 1


def test_missed_slots_older_than_catchup_window_are_skipped(db, make_worker):
    """A stale ledger row — e.g. an entry removed from JOBS_SCHEDULE and
    re-added much later — advances without firing a long-gone slot."""
    yearly = Schedule.from_cron("@yearly")
    job = _TickJob()
    worker = make_worker([(job, yearly)])
    worker.maybe_schedule_jobs()
    ScheduleState.query.filter(schedule_key=schedule_entry_key(job, yearly)).update(
        last_enqueued_slot=timezone.now() - datetime.timedelta(days=730)
    )

    _run_schedule_pass(worker)

    assert not JobRequest.query.exists()
    state = ScheduleState.query.get(schedule_key=schedule_entry_key(job, yearly))
    assert timezone.now() - state.last_enqueued_slot < datetime.timedelta(seconds=60)


def test_catchup_window_is_floored(db, make_worker, settings):
    """A tiny window must not classify ordinary between-pass slots as stale
    and disable scheduling."""
    settings.JOBS_SCHEDULE_CATCHUP_WINDOW = 0
    job = _TickJob()
    worker = make_worker([(job, EVERY_MINUTE)])
    worker.maybe_schedule_jobs()
    _backdate_ledger(job, EVERY_MINUTE, minutes=2)

    _run_schedule_pass(worker)

    assert JobRequest.query.exists()


def test_long_commands_get_distinct_keys(db):
    """The digest is what keeps two long commands with a shared prefix from
    colliding on one ledger row."""
    prefix = "echo " + "x" * 250
    first = ScheduledCommand(prefix + "AAA")
    second = ScheduledCommand(prefix + "BBB")

    assert first.default_concurrency_key() != second.default_concurrency_key()


def test_command_that_fits_keeps_its_raw_key(db):
    """Commands whose slot-stamped key fits the 255-char bound keep the raw
    command as their key — matching what pre-ledger workers produced, so
    slot dedupe holds across the upgrade."""
    command = "x" * 234
    job = ScheduledCommand(command)

    assert job.default_concurrency_key() == command
    slot = timezone.localtime().replace(second=0, microsecond=0)
    assert len(scheduled_concurrency_key(job, slot)) <= 255


def test_legacy_sweep_runs_with_an_empty_schedule(db, make_worker):
    """Pre-ledger transition: a release that removes the last schedule entry
    must still sweep rows an old worker re-created."""
    future_slot = (timezone.localtime() + datetime.timedelta(hours=2)).replace(
        second=0, microsecond=0
    )
    JobRequest.query.create(
        job_class="app.gone.RemovedJob",
        parameters={"args": [], "kwargs": {}},
        queue="default",
        concurrency_key=f":scheduled:{int(future_slot.timestamp())}",
        start_at=future_slot,
    )

    worker = make_worker([])
    worker.maybe_schedule_jobs()

    assert not JobRequest.query.exists()


def test_legacy_future_rows_are_swept_with_provenance(db, make_worker):
    """Pre-ledger transition: a future row an old worker re-created after
    the sweep migration is deleted by the schedule pass — but only when its
    key's slot stamp matches its own start time (true provenance). A user
    row that merely looks similar survives."""
    future_slot = (timezone.localtime() + datetime.timedelta(hours=2)).replace(
        second=0, microsecond=0
    )
    legacy = JobRequest.query.create(
        job_class=jobs_registry.get_job_class_name(_TickJob),
        parameters={"args": [], "kwargs": {}},
        queue="default",
        concurrency_key=f":scheduled:{int(future_slot.timestamp())}",
        start_at=future_slot,
    )
    lookalike = JobRequest.query.create(
        job_class=jobs_registry.get_job_class_name(_TickJob),
        parameters={"args": [], "kwargs": {}},
        queue="default",
        concurrency_key="batch:scheduled:123",
        start_at=future_slot,
    )

    worker = make_worker([(_TickJob(), EVERY_MINUTE)])
    worker.maybe_schedule_jobs()

    remaining = set(JobRequest.query.all().values_list("id", flat=True))
    assert legacy.id not in remaining
    assert lookalike.id in remaining


def test_day_combination_flag_is_part_of_schedule_identity(db):
    """Two keyword schedules differing only in combine_days_with_or match
    different slot sets — they must not collide on one ledger key."""
    and_days = Schedule(day_of_month=15, day_of_week=5)
    or_days = Schedule(day_of_month=15, day_of_week=5, combine_days_with_or=True)
    job = _TickJob()

    assert schedule_entry_key(job, and_days) != schedule_entry_key(job, or_days)
    # And configuring both is legal, not a false duplicate.
    load_schedule([(_TickJob(), and_days), (_TickJob(), or_days)])


def test_prune_chore_deletes_only_stale_ledger_rows(db, settings):
    from plain.jobs.chores import PruneScheduleLedger

    settings.JOBS_SCHEDULE = [(jobs_registry.get_job_class_name(_TickJob), "* * * * *")]
    current_key = schedule_entry_key(_TickJob(), EVERY_MINUTE)
    ScheduleState.query.create(
        schedule_key=current_key, last_enqueued_slot=timezone.now()
    )
    ScheduleState.query.create(
        schedule_key="app.gone.RemovedJob::@daily",
        last_enqueued_slot=timezone.now(),
    )

    PruneScheduleLedger().run()

    assert list(ScheduleState.query.all().values_list("schedule_key", flat=True)) == [
        current_key
    ]


def test_pending_job_for_removed_class_errors_clearly(db):
    """The backstop: a row whose class is gone produces an errored result
    naming JobClassNotRegistered, not a bare KeyError."""
    job_process = JobProcess.query.create(
        job_request_uuid=uuid.uuid4(),
        job_class="app.gone.RemovedJob",
        parameters={"args": [], "kwargs": {}},
        worker_id=uuid.uuid4(),
    )

    result = job_process.run()

    assert result.status == JobResultStatuses.ERRORED
    assert "JobClassNotRegistered" in result.error
