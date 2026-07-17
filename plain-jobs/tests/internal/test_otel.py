"""OTel instrumentation tests for the job enqueue path.

The process (consumer) side runs through `JobProcess.convert_to_result()`
and is exercised by the worker; tests for it would need worker setup and
are deferred. These tests cover `Job.run_in_worker()`, which is the
hottest user-facing path.
"""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager

from opentelemetry.metrics import CallbackOptions
from opentelemetry.trace import SpanKind

from plain.jobs import Job, otel
from plain.jobs.registry import register_job
from plain.jobs.workers import Worker
from plain.test import capture_metrics, capture_spans, override_settings, patch, raises


class _NoopJob(Job):
    def run(self) -> None:
        pass


@register_job
class _BoomJob(Job):
    """Job that always raises — for testing the live ERRORED path end to end.
    Registered so `jobs_registry.load_job` can find it inside JobProcess.run()."""

    def run(self) -> None:
        raise RuntimeError("boom")


class _ExclusiveJob(Job):
    """Job that always reports `should_enqueue=False` to exercise the
    skipped-enqueue branch without needing pre-existing rows."""

    def run(self) -> None:
        pass

    def should_enqueue(self, concurrency_key: str) -> bool:
        return False


def test_enqueue_emits_send_span() -> None:
    with capture_spans() as otel_spans:
        _NoopJob().run_in_worker()

        spans = [s for s in otel_spans.get_finished_spans() if s.name == "send default"]
        assert spans, "expected a `send default` PRODUCER span"
        span = spans[-1]
        attrs = span.attributes
        assert attrs is not None
        assert span.kind == SpanKind.PRODUCER
        assert attrs["messaging.system"] == "plain.jobs"
        assert attrs["messaging.operation.type"] == "send"
        assert attrs["messaging.operation.name"] == "send"
        assert attrs["messaging.destination.name"] == "default"
        assert "messaging.message.id" in attrs
        assert "code.function.name" in attrs


def test_enqueue_skipped_marks_span() -> None:
    with capture_spans() as otel_spans:
        result = _ExclusiveJob().run_in_worker(concurrency_key="busy")

        assert result is None
        span = next(
            s for s in otel_spans.get_finished_spans() if s.name == "send default"
        )
        assert span.attributes is not None
        assert span.attributes["job.enqueue.skipped"] is True


def test_failed_enqueue_marks_producer_span_as_errored() -> None:
    """A failing enqueue's PRODUCER span carries the canonical failure signal:
    status=ERROR plus error.type. Don't branch on exception.escaped — it's
    deprecated upstream and unreliable in the Python SDK."""
    from opentelemetry.trace import StatusCode

    def _boom(*args, **kwargs):
        raise RuntimeError("create failed")

    from plain.jobs.models import JobRequest

    with capture_spans() as otel_spans, patch(JobRequest, "create", _boom):
        with raises(RuntimeError):
            _NoopJob().run_in_worker()

        producer_spans = [
            s for s in otel_spans.get_finished_spans() if s.kind == SpanKind.PRODUCER
        ]
        assert producer_spans, "expected PRODUCER span from run_in_worker()"
        span = producer_spans[-1]
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes is not None
        assert span.attributes["error.type"] == "RuntimeError"
        # Exactly one event — `record_exception=False` on start_as_current_span
        # suppresses the SDK's auto-record so the manual call is the sole event.
        exception_events = [e for e in span.events if e.name == "exception"]
        assert len(exception_events) == 1


def test_failing_job_marks_consumer_span_as_errored() -> None:
    """A failing job's CONSUMER span carries the canonical failure signal:
    status=ERROR plus error.type. The exception is caught inside the span's
    with-block by JobProcess.run, so only the manual record_span_error event
    fires."""
    from opentelemetry.trace import StatusCode

    with capture_spans() as otel_spans:
        request = _BoomJob().run_in_worker()
        assert request is not None
        process = request.convert_to_job_process(worker_id=uuid.uuid4())
        process.run()

        consumer_spans = [
            s for s in otel_spans.get_finished_spans() if s.kind == SpanKind.CONSUMER
        ]
        assert consumer_spans, "expected CONSUMER span from JobProcess.run()"
        span = consumer_spans[-1]
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes is not None
        assert span.attributes["error.type"] == "RuntimeError"
        exception_events = [e for e in span.events if e.name == "exception"]
        assert exception_events


def test_enqueue_failure_records_error_type_on_metric() -> None:
    # The success path defers metric recording to `transaction.on_commit`,
    # which never fires under the test rollback. The failure path records
    # immediately, so it's the one we can assert on here.
    def _boom(*args, **kwargs):
        raise RuntimeError("create failed")

    from plain.jobs.models import JobRequest

    with (
        capture_spans(),
        capture_metrics() as otel_metrics,
        patch(JobRequest, "create", _boom),
    ):
        with raises(RuntimeError):
            _NoopJob().run_in_worker()

        sent_points = otel_metrics.points("messaging.client.sent.messages")
        assert sent_points, "expected sent_messages counter point on failure"
        assert all(
            p.attributes.get("error.type") == "RuntimeError" for p in sent_points
        )
        assert all(
            p.attributes.get("messaging.system") == "plain.jobs" for p in sent_points
        )


# --- process_job lookup failure ---------------------------------------------


def test_process_job_emits_consumer_span_when_lookup_fails() -> None:
    """JobProcess.run() creates the CONSUMER span — but `process_job` does the
    JobProcess row lookup first. A DB transient on that lookup leaves only a
    CLIENT span, which entry-span filtering correctly excludes. The fallback
    CONSUMER span at the top of process_job ensures lookup failures still
    surface."""
    from opentelemetry.trace import StatusCode

    from plain.jobs.workers import process_job

    with capture_spans() as otel_spans:
        # A random UUID won't match any row — JobProcess.query.get raises
        # DoesNotExist, which is the simplest way to exercise the
        # lookup-failure path without monkey-patching the DB.
        process_job(str(uuid.uuid4()))

        spans = [s for s in otel_spans.get_finished_spans() if s.name == "process job"]
        assert len(spans) == 1
        span = spans[0]
        assert span.kind == SpanKind.CONSUMER
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes is not None
        # JobProcess.DoesNotExist via plain-postgres' base manager.
        assert "DoesNotExist" in str(span.attributes["error.type"])
        exception_events = [e for e in span.events if e.name == "exception"]
        assert exception_events


# --- Worker run-loop span -----------------------------------------------


def _build_worker_for_loop_test(
    *, stub_maintenance: bool = True, heartbeat_due: bool = False
) -> Worker:
    """Construct a Worker bypassing __init__ so `_run_loop` can run a single
    iteration without a real ProcessPoolExecutor. Maintenance baselines start
    fresh (nothing due); pass heartbeat_due=True to make the tick open the
    `worker loop` span and run maintenance.
    """
    worker = Worker.__new__(Worker)
    worker.queues = ["default"]
    worker._is_shutting_down = False
    worker._heartbeat_registered = True
    worker._inflight_futures = {}
    worker._inflight_lock = threading.Lock()
    worker.max_processes = 1
    worker.max_pending_per_process = 1
    worker.stats_every = None
    worker.jobs_schedule = []
    worker.worker_id = uuid.uuid4()
    now = time.time()
    worker._heartbeat_at = 0.0 if heartbeat_due else now
    worker._stats_logged_at = now
    worker._job_results_checked_at = now
    worker._jobs_schedule_checked_at = now
    if stub_maintenance:
        worker.maybe_heartbeat = lambda: None
        worker.maybe_log_stats = lambda: None
        worker.maybe_check_job_results = lambda: None
        worker.maybe_schedule_jobs = lambda: None
    return worker


def test_worker_loop_emits_consumer_span_when_maintenance_due() -> None:
    """A tick with maintenance due wraps the work in a `worker loop` CONSUMER
    span — the worker is consuming a recurring maintenance schedule, so its
    failures belong in the canonical entry-span error filter (SERVER /
    CONSUMER / PRODUCER) alongside chores and jobs."""
    from opentelemetry.trace import StatusCode

    worker = _build_worker_for_loop_test(heartbeat_due=True)

    def shutdown_during_heartbeat() -> None:
        worker._is_shutting_down = True

    worker.maybe_heartbeat = shutdown_during_heartbeat  # ty: ignore[invalid-assignment]

    with capture_spans() as otel_spans:
        worker._run_loop()

        loop_spans = [
            s for s in otel_spans.get_finished_spans() if s.name == "worker loop"
        ]
        assert len(loop_spans) == 1
        span = loop_spans[0]
        assert span.kind == SpanKind.CONSUMER
        assert span.status.status_code == StatusCode.UNSET


def test_worker_loop_idle_tick_emits_no_spans() -> None:
    """A fully-idle tick — no maintenance due, empty job poll — exports
    nothing: no `worker loop` span, and no CLIENT spans from the poll query
    or its transaction. This is the invariant that keeps idle workers from
    flooding trace search with single-span root traces."""
    worker = _build_worker_for_loop_test(stub_maintenance=False)

    def shutdown_instead_of_sleeping(seconds: float) -> None:
        worker._is_shutting_down = True

    with (
        capture_spans() as otel_spans,
        patch(time, "sleep", shutdown_instead_of_sleeping),
    ):
        worker._run_loop()

        assert otel_spans.get_finished_spans() == ()


def test_worker_loop_records_error_when_maintenance_fails() -> None:
    """A maintenance exception leaves the loop running and stamps the canonical
    failure signal (status=ERROR + error.type) on the `worker loop` span. This
    is the path that previously swallowed DB transients like the production
    `psycopg.OperationalError` we saw escaping `rescue_job_results`."""
    from opentelemetry.trace import StatusCode

    worker = _build_worker_for_loop_test(heartbeat_due=True)

    def boom_then_shutdown() -> None:
        worker._is_shutting_down = True
        raise RuntimeError("db transient")

    worker.maybe_heartbeat = boom_then_shutdown  # ty: ignore[invalid-assignment]

    with capture_spans() as otel_spans:
        # Must NOT raise — the loop catches and continues, just like in production.
        worker._run_loop()

        loop_spans = [
            s for s in otel_spans.get_finished_spans() if s.name == "worker loop"
        ]
        assert len(loop_spans) == 1
        span = loop_spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes is not None
        assert span.attributes["error.type"] == "RuntimeError"
        exception_events = [e for e in span.events if e.name == "exception"]
        assert exception_events


def test_worker_loop_claim_failure_emits_error_span_and_continues() -> None:
    """A transient DB failure while claiming a job must not kill the worker.
    The loop catches it, emits a one-off `claim job` CONSUMER error span
    (the claim's own CLIENT spans are suppressed, so there is no other entry
    span to carry the failure), and keeps running."""
    from opentelemetry.trace import StatusCode

    from plain.jobs.models import JobRequestQuerySet

    worker = _build_worker_for_loop_test()

    def boom(self) -> None:
        worker._is_shutting_down = True
        raise RuntimeError("db transient")

    with (
        capture_spans() as otel_spans,
        patch(JobRequestQuerySet, "ready_to_run", boom),
        patch(time, "sleep", lambda seconds: None),
    ):
        # Must NOT raise — this used to propagate and crash the worker process.
        worker._run_loop()

        claim_spans = [
            s for s in otel_spans.get_finished_spans() if s.name == "claim job"
        ]
        assert len(claim_spans) == 1
        span = claim_spans[0]
        assert span.kind == SpanKind.CONSUMER
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes is not None
        assert span.attributes["error.type"] == "RuntimeError"
        exception_events = [e for e in span.events if e.name == "exception"]
        assert exception_events


def test_maintenance_due_covers_every_task() -> None:
    """Each maintenance task's due-predicate must independently trigger
    `_maintenance_due` — its OR-list gates whether the worker loop span (and
    the maybe_* calls behind it) run at all, so a predicate dropped from the
    list silently starves that task onto other tasks' cadences."""
    worker = _build_worker_for_loop_test()
    assert not worker._maintenance_due()

    worker._heartbeat_at = 0.0
    assert worker._maintenance_due()
    worker._heartbeat_at = time.time()

    worker.stats_every = 60
    worker._stats_logged_at = 0.0
    assert worker._maintenance_due()
    worker.stats_every = None
    worker._stats_logged_at = time.time()

    worker._job_results_checked_at = 0.0
    assert worker._maintenance_due()
    worker._job_results_checked_at = time.time()

    worker.jobs_schedule = [object()]  # Non-empty is all _schedule_due reads.
    worker._jobs_schedule_checked_at = 0.0
    assert worker._maintenance_due()


def test_future_finished_callback_emits_no_spans() -> None:
    """The done-callback runs on the executor's callback thread with no entry
    span — its bookkeeping queries (an orphan check on every completed job)
    must not export as single-span root traces."""
    from concurrent.futures import Future

    from plain.jobs.workers import future_finished_callback

    with capture_spans() as otel_spans:
        future: Future = Future()
        future.set_result(None)
        future_finished_callback(str(uuid.uuid4()), future)

        assert otel_spans.get_finished_spans() == ()


@register_job
class _AbortedHookQueryJob(Job):
    """on_aborted runs a DB query — used to pin that the hook executes
    outside the done-callback's tracing suppression."""

    def run(self) -> None:
        pass

    def on_aborted(self, result) -> None:
        from plain.jobs.models import JobResult

        JobResult.query.count()


def test_on_aborted_hook_runs_outside_suppression() -> None:
    """The done-callback suppresses framework bookkeeping queries, but
    Job.on_aborted is user code — its DB spans (and query metrics) must
    still export."""
    from concurrent.futures import Future

    from plain.jobs.workers import future_finished_callback

    with capture_spans() as otel_spans:
        request = _AbortedHookQueryJob().run_in_worker()
        assert request is not None
        process = request.convert_to_job_process(worker_id=uuid.uuid4())

        future: Future = Future()
        future.cancel()

    # Isolate the callback from the enqueue/claim spans.
    with capture_spans() as otel_spans:
        future_finished_callback(str(process.uuid), future)

        span_names = [s.name for s in otel_spans.get_finished_spans()]
        # Framework bookkeeping (row lookup, conversion) stays suppressed —
        # the only exported spans are from the user hook's query.
        assert span_names == ["SELECT plainjobs_jobresult"]


# --- Worker-state observable gauges -------------------------------------
#
# Each Worker owns a WorkerMetrics; instantiating one swaps it in as the
# active target for the (process-singleton) registered callbacks. Tests use
# the `_metrics` helper to construct WorkerMetrics around stub Workers and
# restore prior state.


class _StubExecutor:
    def __init__(self, n: int) -> None:
        self._processes = dict.fromkeys(range(n))


class _WorkerStub(Worker):
    """Lightweight Worker for exercising gauge callbacks without spinning up
    a real ProcessPoolExecutor. Skips `Worker.__init__` and only sets what
    the callbacks read."""

    def __init__(self, queues: list[str], num_processes: int = 0) -> None:
        self.queues = queues
        self.executor = _StubExecutor(num_processes)


@contextmanager
def _metrics():
    """Construct a `WorkerMetrics` around a stub Worker; restore prior state."""

    def _make(worker):
        return otel.WorkerMetrics(worker)

    with patch(otel.WorkerMetrics, "_current", otel.WorkerMetrics._current):
        yield _make


def _by_queue(callback) -> dict[str, float]:
    return {
        (o.attributes or {})["messaging.destination.name"]: o.value
        for o in callback(CallbackOptions())
    }


def test_worker_processes_gauge_reports_pool_size() -> None:
    with _metrics() as metrics:
        metrics(_WorkerStub(queues=["default"], num_processes=3))
        obs = list(otel.WorkerMetrics._gauge_worker_processes(CallbackOptions()))
        assert len(obs) == 1
        assert obs[0].value == 3


def test_gauges_return_empty_when_no_active_metrics() -> None:
    """The active-instance indirection is the whole reason this exists; verify
    each gauge returns no observations when nothing is active."""
    with patch(otel.WorkerMetrics, "_current", None):
        for callback in (
            otel.WorkerMetrics._gauge_worker_processes,
            otel.WorkerMetrics._gauge_queue_depth,
            otel.WorkerMetrics._gauge_queue_oldest_age,
            otel.WorkerMetrics._gauge_queue_scheduled,
            otel.WorkerMetrics._gauge_running,
        ):
            assert list(callback(CallbackOptions())) == []


# Every @_gauge_db_queries-decorated callback. Shared by the tests that pin
# that decorator's behavior so a new DB-backed gauge can't be added to one
# invariant but not the other.
_DB_GAUGE_CALLBACKS = (
    otel.WorkerMetrics._gauge_queue_depth,
    otel.WorkerMetrics._gauge_queue_oldest_age,
    otel.WorkerMetrics._gauge_queue_scheduled,
    otel.WorkerMetrics._gauge_running,
    otel.WorkerMetrics._gauge_workers,
)


def test_gauge_callbacks_emit_no_spans() -> None:
    """Gauge callbacks run on the metric-reader thread with no entry span
    active — their DB queries must not export as single-span root traces."""
    with _metrics() as metrics, capture_spans() as otel_spans:
        metrics(_WorkerStub(queues=["default"]))

        for callback in _DB_GAUGE_CALLBACKS:
            list(callback(CallbackOptions()))

        assert otel_spans.get_finished_spans() == ()


def test_queue_depth_counts_ready_jobs_by_queue() -> None:
    with _metrics() as metrics:
        _NoopJob().run_in_worker()  # default queue
        _NoopJob().run_in_worker()  # default queue

        metrics(_WorkerStub(queues=["default"]))
        assert _by_queue(otel.WorkerMetrics._gauge_queue_depth) == {"default": 2}


def test_gauges_emit_zero_for_empty_handled_queues() -> None:
    """Empty queues still need an observation so dashboards using
    `last_value` don't show stale non-zero readings after a drain."""
    with _metrics() as metrics:
        metrics(_WorkerStub(queues=["default", "priority"]))

        for callback in (
            otel.WorkerMetrics._gauge_queue_depth,
            otel.WorkerMetrics._gauge_queue_scheduled,
            otel.WorkerMetrics._gauge_running,
            otel.WorkerMetrics._gauge_queue_oldest_age,
        ):
            assert _by_queue(callback) == {"default": 0, "priority": 0}


def test_queue_scheduled_counts_future_jobs_only() -> None:
    import datetime

    with _metrics() as metrics:
        # One ready, one scheduled for an hour from now.
        _NoopJob().run_in_worker()
        _NoopJob().run_in_worker(delay=datetime.timedelta(hours=1))

        metrics(_WorkerStub(queues=["default"]))
        assert _by_queue(otel.WorkerMetrics._gauge_queue_depth) == {"default": 1}
        assert _by_queue(otel.WorkerMetrics._gauge_queue_scheduled) == {"default": 1}


def test_queue_oldest_age_returns_seconds() -> None:
    with _metrics() as metrics:
        _NoopJob().run_in_worker()

        metrics(_WorkerStub(queues=["default"]))
        obs = list(otel.WorkerMetrics._gauge_queue_oldest_age(CallbackOptions()))
        assert len(obs) == 1
        assert (obs[0].attributes or {})["messaging.destination.name"] == "default"
        # The job was just enqueued, so age is small but >= 0.
        assert obs[0].value >= 0


def test_metrics_swap_routes_callbacks_to_current_instance() -> None:
    """Reload paths shut down one Worker and construct another in the same
    process. Each new WorkerMetrics swaps in as the current target;
    callbacks always read from the latest instance."""
    with _metrics() as metrics:
        metrics(_WorkerStub(queues=["queue-a"]))
        assert set(_by_queue(otel.WorkerMetrics._gauge_queue_depth)) == {"queue-a"}

        metrics(_WorkerStub(queues=["queue-b"]))
        assert set(_by_queue(otel.WorkerMetrics._gauge_queue_depth)) == {"queue-b"}


def _trigger_outcome(status: str) -> None:
    """Take a JobRequest through to a terminal JobResult with the given status."""
    request = _NoopJob().run_in_worker()
    assert request is not None
    process = request.convert_to_job_process(worker_id=uuid.uuid4())
    process.convert_to_result(status=status)


def test_consumed_counter_records_outcome_for_lost() -> None:
    """Rescue-path LOST conversions show up in the consumed counter with
    plain.jobs.outcome=lost. Without this, dashboards counting throughput
    via the semconv counter would silently miss every rescued job."""
    from plain.jobs.models import JobResultStatuses

    with capture_metrics() as otel_metrics:
        _trigger_outcome(JobResultStatuses.LOST)

        points = otel_metrics.points("messaging.client.consumed.messages")
        lost_points = [
            p for p in points if p.attributes.get("plain.jobs.outcome") == "lost"
        ]
        assert lost_points, "expected a consumed counter point with outcome=lost"
        assert all(
            p.attributes.get("messaging.system") == "plain.jobs" for p in lost_points
        )
        assert all(
            p.attributes.get("messaging.destination.name") == "default"
            for p in lost_points
        )


def test_consumed_counter_records_outcome_for_cancelled() -> None:
    from plain.jobs.models import JobResultStatuses

    with capture_metrics() as otel_metrics:
        _trigger_outcome(JobResultStatuses.CANCELLED)

        points = otel_metrics.points("messaging.client.consumed.messages")
        cancelled = [
            p for p in points if p.attributes.get("plain.jobs.outcome") == "cancelled"
        ]
        assert cancelled, "expected a consumed counter point with outcome=cancelled"


def test_consumed_counter_records_outcome_for_successful() -> None:
    """SUCCESSFUL conversions tick the consumed counter — covers the live
    convert_to_result path that the counter call now lives in."""
    from plain.jobs.models import JobResultStatuses

    with capture_metrics() as otel_metrics:
        _trigger_outcome(JobResultStatuses.SUCCESSFUL)

        points = otel_metrics.points("messaging.client.consumed.messages")
        successful = [
            p for p in points if p.attributes.get("plain.jobs.outcome") == "successful"
        ]
        assert successful, "expected a consumed counter point with outcome=successful"


def test_consumed_counter_records_outcome_for_errored() -> None:
    from plain.jobs.models import JobResultStatuses

    with capture_metrics() as otel_metrics:
        _trigger_outcome(JobResultStatuses.ERRORED)

        points = otel_metrics.points("messaging.client.consumed.messages")
        errored = [
            p for p in points if p.attributes.get("plain.jobs.outcome") == "errored"
        ]
        assert errored, "expected a consumed counter point with outcome=errored"


def test_consumed_counter_includes_error_type_when_job_raises() -> None:
    """When the live path catches an exception, the resulting consumed
    counter point carries error.type alongside outcome=errored — same
    semconv pattern the operation_duration histogram already follows."""
    with capture_metrics() as otel_metrics:
        request = _BoomJob().run_in_worker()
        assert request is not None
        process = request.convert_to_job_process(worker_id=uuid.uuid4())
        process.run()

        # Counters are cumulative across tests in a process and the SDK
        # splits by attribute set, so other tests may have produced errored
        # points without `error.type`. Look for a point that carries both
        # attributes.
        points = otel_metrics.points("messaging.client.consumed.messages")
        matching = [
            p
            for p in points
            if p.attributes.get("plain.jobs.outcome") == "errored"
            and p.attributes.get("error.type") == "RuntimeError"
        ]
        assert matching, (
            "expected a consumed counter point with outcome=errored and error.type=RuntimeError"
        )


def test_consumed_counter_records_outcome_for_deferred() -> None:
    """DEFERRED bypasses convert_to_result — defer() builds the JobResult
    directly, so this test pins the explicit record_consumed call in defer()."""
    from plain.jobs.exceptions import DeferJob

    with capture_metrics() as otel_metrics:
        request = _NoopJob().run_in_worker()
        assert request is not None
        process = request.convert_to_job_process(worker_id=uuid.uuid4())
        process.defer(job=_NoopJob(), defer_exception=DeferJob(delay=60))

        points = otel_metrics.points("messaging.client.consumed.messages")
        deferred = [
            p for p in points if p.attributes.get("plain.jobs.outcome") == "deferred"
        ]
        assert deferred, "expected a consumed counter point with outcome=deferred"


def test_defer_skipped_when_reenqueue_blocked() -> None:
    """When defer()'s re-enqueue is blocked by should_enqueue() returning
    False, the framework honors the signal silently — same convention as
    run_in_worker() and retry_job(), which both return None in the same
    situation. The result is recorded as DEFERRED with no retry uuid so
    the case is visible in admin without surfacing as an exception."""
    from plain.jobs.exceptions import DeferJob
    from plain.jobs.models import JobResultStatuses

    # Seed a JobProcess via a job whose should_enqueue allows it through.
    request = _NoopJob().run_in_worker(concurrency_key="busy")
    assert request is not None
    process = request.convert_to_job_process(worker_id=uuid.uuid4())

    # Defer using a job that always says should_enqueue=False. In
    # production these would be the same class; using two here lets the
    # initial enqueue succeed and only the re-enqueue get blocked.
    result = process.defer(
        job=_ExclusiveJob(),
        defer_exception=DeferJob(delay=60),
    )

    assert result.status == JobResultStatuses.DEFERRED
    assert result.retry_job_request_uuid is None
    assert "re-enqueue skipped" in result.error


def test_workers_gauge_splits_by_state_attribute() -> None:
    """One `plain.jobs.workers` gauge with `plain.jobs.worker.state` attribute
    distinguishing active vs. stale rows. One snapshot of the cutoff means a
    boundary row can't end up in both states."""
    import datetime
    import socket

    from plain.jobs.models import WorkerHeartbeat
    from plain.utils import timezone

    with _metrics() as metrics, override_settings(JOBS_HEARTBEAT_TIMEOUT=60):
        metrics(_WorkerStub(queues=["default"]))

        now = timezone.now()
        # Two within the cutoff, one past it.
        for age in (5, 30):
            WorkerHeartbeat.query.create(
                worker_id=uuid.uuid4(),
                hostname=socket.gethostname(),
                pid=12345,
                queues=["default"],
                last_heartbeat_at=now - datetime.timedelta(seconds=age),
            )
        WorkerHeartbeat.query.create(
            worker_id=uuid.uuid4(),
            hostname=socket.gethostname(),
            pid=67890,
            queues=["default"],
            last_heartbeat_at=now - datetime.timedelta(seconds=86400),
        )

        by_state = {
            (o.attributes or {})["plain.jobs.worker.state"]: o.value
            for o in otel.WorkerMetrics._gauge_workers(CallbackOptions())
        }
        assert by_state == {"active": 2, "stale": 1}


def test_running_counts_started_jobprocess_rows_by_queue() -> None:
    """`plain.jobs.running` only counts JobProcesses that have actually started
    (`started_at` set inside `process_job`), matching `JobProcess.query.running()`.
    JobProcesses pulled from the queue but still waiting for a pool slot don't
    count."""
    from plain.utils import timezone

    with _metrics() as metrics:
        request = _NoopJob().run_in_worker()
        assert request is not None
        process = request.convert_to_job_process(worker_id=uuid.uuid4())

        metrics(_WorkerStub(queues=["default"]))

        # Pre-pickup: not yet running — gauge still emits 0 for the handled queue.
        assert _by_queue(otel.WorkerMetrics._gauge_running) == {"default": 0}

        # Worker picks it up; `process_job` sets started_at.
        process.started_at = timezone.now()
        process.update(fields=["started_at"])

        assert _by_queue(otel.WorkerMetrics._gauge_running) == {"default": 1}


def test_db_gauge_callbacks_release_their_connection() -> None:
    """Each DB-touching gauge callback returns its pooled connection when it
    finishes (see `_gauge_db_queries` for why this matters)."""
    released = 0

    def _counting_release(*args, **kwargs) -> None:
        nonlocal released
        released += 1

    with (
        _metrics() as metrics,
        patch(otel, "return_database_connection", _counting_release),
    ):
        metrics(_WorkerStub(queues=["default"]))
        for callback in _DB_GAUGE_CALLBACKS:
            list(callback(CallbackOptions()))

        assert released == len(_DB_GAUGE_CALLBACKS)
