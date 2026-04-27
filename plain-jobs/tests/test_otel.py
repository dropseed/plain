"""OTel instrumentation tests for the job enqueue path.

The process (consumer) side runs through `JobProcess.convert_to_result()`
and is exercised by the worker; tests for it would need worker setup and
are deferred. These tests cover `Job.run_in_worker()`, which is the
hottest user-facing path.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind

from plain.jobs import Job


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
