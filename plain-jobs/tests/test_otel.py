"""OTel instrumentation tests for the job enqueue path.

The process (consumer) side runs through `JobProcess.convert_to_result()`
and is exercised by the worker; tests for it would need worker setup and
are deferred. These tests cover `Job.run_in_worker()`, which is the
hottest user-facing path.
"""

from __future__ import annotations

import pytest
from opentelemetry.metrics import CallbackOptions
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind

from plain.jobs import Job, otel
from plain.jobs.workers import Worker


class _NoopJob(Job):
    def run(self) -> None:
        pass


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

    data = otel_metrics.get_metrics_data()
    assert data is not None
    sent_points = [
        p
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == "messaging.client.sent.messages"
        for p in m.data.data_points
    ]
    assert sent_points, "expected sent_messages counter point on failure"
    assert all(p.attributes.get("error.type") == "RuntimeError" for p in sent_points)
    assert all(
        p.attributes.get("messaging.system") == "plain.jobs" for p in sent_points
    )


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


@pytest.mark.usefixtures("db")
def test_running_counts_started_jobprocess_rows_by_queue(metrics) -> None:
    """`plain.jobs.running` only counts JobProcesses that have actually started
    (`started_at` set inside `process_job`), matching `JobProcess.query.running()`.
    JobProcesses pulled from the queue but still waiting for a pool slot don't
    count."""
    from plain.utils import timezone

    request = _NoopJob().run_in_worker()
    assert request is not None
    process = request.convert_to_job_process()

    metrics(_WorkerStub(queues=["default"]))

    # Pre-pickup: not yet running — gauge still emits 0 for the handled queue.
    assert _by_queue(otel.WorkerMetrics._gauge_running) == {"default": 0}

    # Worker picks it up; `process_job` sets started_at.
    process.started_at = timezone.now()
    process.save(update_fields=["started_at"])

    assert _by_queue(otel.WorkerMetrics._gauge_running) == {"default": 1}
