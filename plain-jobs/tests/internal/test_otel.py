"""OTel instrumentation tests for the job enqueue path.

The process (consumer) side runs through `JobProcess.convert_to_result()`
and is exercised by the worker; tests for it would need worker setup and
are deferred. These tests cover `Job.run_in_worker()`, which is the
hottest user-facing path.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from opentelemetry.metrics import CallbackOptions
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind

from plain.jobs import Job, otel
from plain.jobs.registry import register_job
from plain.jobs.workers import Worker


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


@pytest.mark.usefixtures("db")
def test_enqueue_emits_send_span(otel_spans: InMemorySpanExporter) -> None:
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


@pytest.mark.usefixtures("db")
def test_enqueue_skipped_marks_span(otel_spans: InMemorySpanExporter) -> None:
    result = _ExclusiveJob().run_in_worker(concurrency_key="busy")

    assert result is None
    span = next(s for s in otel_spans.get_finished_spans() if s.name == "send default")
    assert span.attributes is not None
    assert span.attributes["job.enqueue.skipped"] is True


@pytest.mark.usefixtures("db")
def test_failed_enqueue_marks_producer_span_as_errored(
    monkeypatch: pytest.MonkeyPatch,
    otel_spans: InMemorySpanExporter,
) -> None:
    """A failing enqueue's PRODUCER span carries the canonical failure signal:
    status=ERROR plus error.type. Don't branch on exception.escaped — it's
    deprecated upstream and unreliable in the Python SDK."""
    from opentelemetry.trace import StatusCode

    def _boom(*args, **kwargs):
        raise RuntimeError("save failed")

    from plain.jobs.models import JobRequest

    monkeypatch.setattr(JobRequest, "save", _boom)

    with pytest.raises(RuntimeError):
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


@pytest.mark.usefixtures("db")
def test_failing_job_marks_consumer_span_as_errored(
    otel_spans: InMemorySpanExporter,
) -> None:
    """A failing job's CONSUMER span carries the canonical failure signal:
    status=ERROR plus error.type. The exception is caught inside the span's
    with-block by JobProcess.run, so only the manual record_span_error event
    fires."""
    from opentelemetry.trace import StatusCode

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


@pytest.mark.usefixtures("db")
def test_enqueue_failure_records_error_type_on_metric(
    monkeypatch: pytest.MonkeyPatch,
    otel_spans: InMemorySpanExporter,
    otel_metrics: InMemoryMetricReader,
) -> None:
    # The success path defers metric recording to `transaction.on_commit`,
    # which never fires under the test rollback. The failure path records
    # immediately, so it's the one we can assert on here.
    def _boom(*args, **kwargs):
        raise RuntimeError("save failed")

    from plain.jobs.models import JobRequest

    monkeypatch.setattr(JobRequest, "save", _boom)

    with pytest.raises(RuntimeError):
        _NoopJob().run_in_worker()

    sent_points = _metric_points(otel_metrics, "messaging.client.sent.messages")
    assert sent_points, "expected sent_messages counter point on failure"
    assert all(p.attributes.get("error.type") == "RuntimeError" for p in sent_points)
    assert all(
        p.attributes.get("messaging.system") == "plain.jobs" for p in sent_points
    )


# --- Worker run-loop span -----------------------------------------------


def _build_worker_for_loop_test() -> Worker:
    """Construct a Worker bypassing __init__ so `_run_loop` can run a single
    iteration without a real ProcessPoolExecutor. Tests override the maintenance
    methods to control when the loop exits."""
    worker = Worker.__new__(Worker)
    worker.queues = ["default"]
    worker._is_shutting_down = False
    worker._heartbeat_registered = True
    worker._inflight_futures = {}
    worker._inflight_lock = threading.Lock()
    worker.max_processes = 1
    worker.max_pending_per_process = 1
    worker.maybe_heartbeat = lambda: None
    worker.maybe_log_stats = lambda: None
    worker.maybe_check_job_results = lambda: None
    worker.maybe_schedule_jobs = lambda: None
    return worker


@pytest.mark.usefixtures("db")
def test_worker_loop_emits_internal_span_per_iteration(
    otel_spans: InMemorySpanExporter,
) -> None:
    """Each worker loop iteration wraps the maintenance work in a `worker loop`
    INTERNAL span so DB transients during maintenance land on a span."""
    from opentelemetry.trace import StatusCode

    worker = _build_worker_for_loop_test()

    def shutdown_during_heartbeat() -> None:
        worker._is_shutting_down = True

    worker.maybe_heartbeat = shutdown_during_heartbeat  # ty: ignore[invalid-assignment]
    worker._run_loop()

    loop_spans = [s for s in otel_spans.get_finished_spans() if s.name == "worker loop"]
    assert len(loop_spans) == 1
    span = loop_spans[0]
    assert span.kind == SpanKind.INTERNAL
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.usefixtures("db")
def test_worker_loop_records_error_when_maintenance_fails(
    otel_spans: InMemorySpanExporter,
) -> None:
    """A maintenance exception leaves the loop running and stamps the canonical
    failure signal (status=ERROR + error.type) on the `worker loop` span. This
    is the path that previously swallowed DB transients like the production
    `psycopg.OperationalError` we saw escaping `rescue_job_results`."""
    from opentelemetry.trace import StatusCode

    worker = _build_worker_for_loop_test()

    def boom_then_shutdown() -> None:
        worker._is_shutting_down = True
        raise RuntimeError("db transient")

    worker.maybe_heartbeat = boom_then_shutdown  # ty: ignore[invalid-assignment]
    # Must NOT raise — the loop catches and continues, just like in production.
    worker._run_loop()

    loop_spans = [s for s in otel_spans.get_finished_spans() if s.name == "worker loop"]
    assert len(loop_spans) == 1
    span = loop_spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "RuntimeError"
    exception_events = [e for e in span.events if e.name == "exception"]
    assert exception_events


# --- Worker-state observable gauges -------------------------------------
#
# Each Worker owns a WorkerMetrics; instantiating one swaps it in as the
# active target for the (process-singleton) registered callbacks. Tests use
# the `metrics` fixture to construct WorkerMetrics around stub Workers and
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
        self.executor = _StubExecutor(num_processes)  # type: ignore[assignment]


@pytest.fixture
def metrics():
    """Construct a `WorkerMetrics` around a stub Worker; restore prior state."""
    saved = otel.WorkerMetrics._current

    def _make(worker):
        return otel.WorkerMetrics(worker)

    yield _make
    otel.WorkerMetrics._current = saved


def _by_queue(callback) -> dict[str, float]:
    return {
        (o.attributes or {})["messaging.destination.name"]: o.value
        for o in callback(CallbackOptions())
    }


@pytest.mark.usefixtures("db")
def test_worker_processes_gauge_reports_pool_size(metrics) -> None:
    metrics(_WorkerStub(queues=["default"], num_processes=3))
    obs = list(otel.WorkerMetrics._gauge_worker_processes(CallbackOptions()))
    assert len(obs) == 1
    assert obs[0].value == 3


@pytest.mark.usefixtures("db")
def test_gauges_return_empty_when_no_active_metrics() -> None:
    """The active-instance indirection is the whole reason this exists; verify
    each gauge returns no observations when nothing is active."""
    saved = otel.WorkerMetrics._current
    otel.WorkerMetrics._current = None
    try:
        for callback in (
            otel.WorkerMetrics._gauge_worker_processes,
            otel.WorkerMetrics._gauge_queue_depth,
            otel.WorkerMetrics._gauge_queue_oldest_age,
            otel.WorkerMetrics._gauge_queue_scheduled,
            otel.WorkerMetrics._gauge_running,
        ):
            assert list(callback(CallbackOptions())) == []
    finally:
        otel.WorkerMetrics._current = saved


@pytest.mark.usefixtures("db")
def test_queue_depth_counts_ready_jobs_by_queue(metrics) -> None:
    _NoopJob().run_in_worker()  # default queue
    _NoopJob().run_in_worker()  # default queue

    metrics(_WorkerStub(queues=["default"]))
    assert _by_queue(otel.WorkerMetrics._gauge_queue_depth) == {"default": 2}


@pytest.mark.usefixtures("db")
def test_gauges_emit_zero_for_empty_handled_queues(metrics) -> None:
    """Empty queues still need an observation so dashboards using
    `last_value` don't show stale non-zero readings after a drain."""
    metrics(_WorkerStub(queues=["default", "priority"]))

    for callback in (
        otel.WorkerMetrics._gauge_queue_depth,
        otel.WorkerMetrics._gauge_queue_scheduled,
        otel.WorkerMetrics._gauge_running,
        otel.WorkerMetrics._gauge_queue_oldest_age,
    ):
        assert _by_queue(callback) == {"default": 0, "priority": 0}


@pytest.mark.usefixtures("db")
def test_queue_scheduled_counts_future_jobs_only(metrics) -> None:
    import datetime

    # One ready, one scheduled for an hour from now.
    _NoopJob().run_in_worker()
    _NoopJob().run_in_worker(delay=datetime.timedelta(hours=1))

    metrics(_WorkerStub(queues=["default"]))
    assert _by_queue(otel.WorkerMetrics._gauge_queue_depth) == {"default": 1}
    assert _by_queue(otel.WorkerMetrics._gauge_queue_scheduled) == {"default": 1}


@pytest.mark.usefixtures("db")
def test_queue_oldest_age_returns_seconds(metrics) -> None:
    _NoopJob().run_in_worker()

    metrics(_WorkerStub(queues=["default"]))
    obs = list(otel.WorkerMetrics._gauge_queue_oldest_age(CallbackOptions()))
    assert len(obs) == 1
    assert (obs[0].attributes or {})["messaging.destination.name"] == "default"
    # The job was just enqueued, so age is small but >= 0.
    assert obs[0].value >= 0


@pytest.mark.usefixtures("db")
def test_metrics_swap_routes_callbacks_to_current_instance(metrics) -> None:
    """Reload paths shut down one Worker and construct another in the same
    process. Each new WorkerMetrics swaps in as the current target;
    callbacks always read from the latest instance."""
    metrics(_WorkerStub(queues=["queue-a"]))
    assert set(_by_queue(otel.WorkerMetrics._gauge_queue_depth)) == {"queue-a"}

    metrics(_WorkerStub(queues=["queue-b"]))
    assert set(_by_queue(otel.WorkerMetrics._gauge_queue_depth)) == {"queue-b"}


def _metric_points(otel_metrics: InMemoryMetricReader, name: str) -> list:
    """Return all data points for a named metric across the export."""
    data = otel_metrics.get_metrics_data()
    if data is None:
        return []
    return [
        p
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == name
        for p in m.data.data_points
    ]


def _trigger_outcome(status: str) -> None:
    """Take a JobRequest through to a terminal JobResult with the given status."""
    request = _NoopJob().run_in_worker()
    assert request is not None
    process = request.convert_to_job_process(worker_id=uuid.uuid4())
    process.convert_to_result(status=status)


@pytest.mark.usefixtures("db")
def test_consumed_counter_records_outcome_for_lost(
    otel_metrics: InMemoryMetricReader,
) -> None:
    """Rescue-path LOST conversions show up in the consumed counter with
    plain.jobs.outcome=lost. Without this, dashboards counting throughput
    via the semconv counter would silently miss every rescued job."""
    from plain.jobs.models import JobResultStatuses

    _trigger_outcome(JobResultStatuses.LOST)

    points = _metric_points(otel_metrics, "messaging.client.consumed.messages")
    lost_points = [
        p for p in points if p.attributes.get("plain.jobs.outcome") == "lost"
    ]
    assert lost_points, "expected a consumed counter point with outcome=lost"
    assert all(
        p.attributes.get("messaging.system") == "plain.jobs" for p in lost_points
    )
    assert all(
        p.attributes.get("messaging.destination.name") == "default" for p in lost_points
    )


@pytest.mark.usefixtures("db")
def test_consumed_counter_records_outcome_for_cancelled(
    otel_metrics: InMemoryMetricReader,
) -> None:
    from plain.jobs.models import JobResultStatuses

    _trigger_outcome(JobResultStatuses.CANCELLED)

    points = _metric_points(otel_metrics, "messaging.client.consumed.messages")
    cancelled = [
        p for p in points if p.attributes.get("plain.jobs.outcome") == "cancelled"
    ]
    assert cancelled, "expected a consumed counter point with outcome=cancelled"


@pytest.mark.usefixtures("db")
def test_consumed_counter_records_outcome_for_successful(
    otel_metrics: InMemoryMetricReader,
) -> None:
    """SUCCESSFUL conversions tick the consumed counter — covers the live
    convert_to_result path that the counter call now lives in."""
    from plain.jobs.models import JobResultStatuses

    _trigger_outcome(JobResultStatuses.SUCCESSFUL)

    points = _metric_points(otel_metrics, "messaging.client.consumed.messages")
    successful = [
        p for p in points if p.attributes.get("plain.jobs.outcome") == "successful"
    ]
    assert successful, "expected a consumed counter point with outcome=successful"


@pytest.mark.usefixtures("db")
def test_consumed_counter_records_outcome_for_errored(
    otel_metrics: InMemoryMetricReader,
) -> None:
    from plain.jobs.models import JobResultStatuses

    _trigger_outcome(JobResultStatuses.ERRORED)

    points = _metric_points(otel_metrics, "messaging.client.consumed.messages")
    errored = [p for p in points if p.attributes.get("plain.jobs.outcome") == "errored"]
    assert errored, "expected a consumed counter point with outcome=errored"


@pytest.mark.usefixtures("db")
def test_consumed_counter_includes_error_type_when_job_raises(
    otel_metrics: InMemoryMetricReader,
) -> None:
    """When the live path catches an exception, the resulting consumed
    counter point carries error.type alongside outcome=errored — same
    semconv pattern the operation_duration histogram already follows."""
    request = _BoomJob().run_in_worker()
    assert request is not None
    process = request.convert_to_job_process(worker_id=uuid.uuid4())
    process.run()

    # Counters are cumulative across tests in a process and the SDK splits
    # by attribute set, so other tests may have produced errored points
    # without `error.type`. Look for a point that carries both attributes.
    points = _metric_points(otel_metrics, "messaging.client.consumed.messages")
    matching = [
        p
        for p in points
        if p.attributes.get("plain.jobs.outcome") == "errored"
        and p.attributes.get("error.type") == "RuntimeError"
    ]
    assert matching, (
        "expected a consumed counter point with outcome=errored and error.type=RuntimeError"
    )


@pytest.mark.usefixtures("db")
def test_consumed_counter_records_outcome_for_deferred(
    otel_metrics: InMemoryMetricReader,
) -> None:
    """DEFERRED bypasses convert_to_result — defer() builds the JobResult
    directly, so this test pins the explicit record_consumed call in defer()."""
    from plain.jobs.exceptions import DeferJob

    request = _NoopJob().run_in_worker()
    assert request is not None
    process = request.convert_to_job_process(worker_id=uuid.uuid4())
    process.defer(job=_NoopJob(), defer_exception=DeferJob(delay=60))

    points = _metric_points(otel_metrics, "messaging.client.consumed.messages")
    deferred = [
        p for p in points if p.attributes.get("plain.jobs.outcome") == "deferred"
    ]
    assert deferred, "expected a consumed counter point with outcome=deferred"


@pytest.mark.usefixtures("db")
def test_workers_gauge_splits_by_state_attribute(metrics, settings) -> None:
    """One `plain.jobs.workers` gauge with `plain.jobs.worker.state` attribute
    distinguishing active vs. stale rows. One snapshot of the cutoff means a
    boundary row can't end up in both states."""
    import datetime
    import socket

    from plain.jobs.models import WorkerHeartbeat
    from plain.utils import timezone

    settings.JOBS_HEARTBEAT_TIMEOUT = 60
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


@pytest.mark.usefixtures("db")
def test_running_counts_started_jobprocess_rows_by_queue(metrics) -> None:
    """`plain.jobs.running` only counts JobProcesses that have actually started
    (`started_at` set inside `process_job`), matching `JobProcess.query.running()`.
    JobProcesses pulled from the queue but still waiting for a pool slot don't
    count."""
    from plain.utils import timezone

    request = _NoopJob().run_in_worker()
    assert request is not None
    process = request.convert_to_job_process(worker_id=uuid.uuid4())

    metrics(_WorkerStub(queues=["default"]))

    # Pre-pickup: not yet running — gauge still emits 0 for the handled queue.
    assert _by_queue(otel.WorkerMetrics._gauge_running) == {"default": 0}

    # Worker picks it up; `process_job` sets started_at.
    process.started_at = timezone.now()
    process.save(update_fields=["started_at"])

    assert _by_queue(otel.WorkerMetrics._gauge_running) == {"default": 1}
