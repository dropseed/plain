from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_FUNCTION_NAME,
)
from opentelemetry.semconv._incubating.attributes.messaging_attributes import (
    MESSAGING_DESTINATION_NAME,
    MESSAGING_OPERATION_TYPE,
    MESSAGING_SYSTEM,
    MessagingOperationTypeValues,
)
from opentelemetry.semconv._incubating.metrics.messaging_metrics import (
    create_messaging_client_consumed_messages,
    create_messaging_client_operation_duration,
    create_messaging_client_sent_messages,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

from plain.postgres import Q
from plain.postgres.aggregates import Count, Min
from plain.utils import timezone
from plain.utils.otel import format_exception_type

if TYPE_CHECKING:
    from .models import JobResult
    from .workers import Worker

# Attribute key for the terminal-status dimension on the consumed counter.
PLAIN_JOBS_OUTCOME = "plain.jobs.outcome"

# Attribute key for the worker-liveness dimension on plain.jobs.workers.
PLAIN_JOBS_WORKER_STATE = "plain.jobs.worker.state"

try:
    _package_version = importlib.metadata.version("plain.jobs")
except importlib.metadata.PackageNotFoundError:
    _package_version = "dev"

tracer = trace.get_tracer("plain.jobs", _package_version)
meter = metrics.get_meter("plain.jobs", version=_package_version)

# Per-event instruments (semconv messaging metrics + plain.jobs queue.wait.duration).
sent_messages_counter = create_messaging_client_sent_messages(meter)
consumed_messages_counter = create_messaging_client_consumed_messages(meter)
operation_duration_histogram = create_messaging_client_operation_duration(meter)
queue_wait_duration_histogram = meter.create_histogram(
    name="plain.jobs.queue.wait.duration",
    unit="s",
    description="Time a job spent waiting in the queue before a worker picked it up.",
)


def record_span_error(
    span: trace.Span,
    exc: BaseException,
    metric_attributes: dict[str, Any],
) -> str:
    """Mark the span as failed, stamp error.type on it and on the per-call
    metric attribute dict, and return the error.type string so the caller
    can forward it to other instruments."""
    error_type = format_exception_type(exc)
    span.record_exception(exc)
    span.set_status(trace.StatusCode.ERROR)
    span.set_attribute(ERROR_TYPE, error_type)
    metric_attributes[ERROR_TYPE] = error_type
    return error_type


def process_metric_attributes(queue: str, job_class: str) -> dict[str, Any]:
    """Base attribute dict for messaging.client.* process-side metrics.

    Shared by JobProcess.run() (which adds error.type for failed jobs) and
    record_consumed (which adds the outcome dimension). One builder so
    keys/values stay in lockstep across the two call sites.
    """
    return {
        MESSAGING_SYSTEM: "plain.jobs",
        MESSAGING_OPERATION_TYPE: MessagingOperationTypeValues.PROCESS.value,
        MESSAGING_DESTINATION_NAME: queue,
        CODE_FUNCTION_NAME: f"{job_class}.run",
    }


def record_consumed(result: JobResult, *, error_type: str | None = None) -> None:
    """Record one consumed-message metric point per terminal JobResult.

    `plain.jobs.outcome` carries the terminal status (successful/errored/
    lost/cancelled/deferred). `error.type` is included when known — i.e.,
    when the live path caught an exception and forwarded it through. The
    rescue path (LOST) and direct cancellations don't carry an error type
    because there is no exception object to derive it from."""
    attrs = process_metric_attributes(result.queue, result.job_class)
    attrs[PLAIN_JOBS_OUTCOME] = result.status.lower()
    if error_type is not None:
        attrs[ERROR_TYPE] = error_type
    consumed_messages_counter.add(1, attrs)


class WorkerMetrics:
    """Per-Worker observable gauges (queue depth/age/scheduled, running count,
    worker process count).

    The OTel SDK keeps the *first* callback registered for a given instrument
    name, so instruments are registered once per process. The Worker they
    observe may change across reload paths, so each Worker owns a
    WorkerMetrics; constructing one swaps it in as the active target for the
    (process-singleton) callbacks. The new instance simply replaces the old
    one in the class-level `_current` slot — no explicit teardown is needed
    because either a successor swaps in (reload) or the process exits
    (signal shutdown).

    Each callback emits one observation per queue this Worker handles, every
    export interval, including zero for empty queues so `last_value`
    dashboards don't show stale readings after a drain. When two Workers
    handle the same queue they emit identical values; aggregate with
    `last_value`/`max`, never `sum`.
    """

    _current: ClassVar[WorkerMetrics | None] = None
    _registered: ClassVar[bool] = False

    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        type(self)._register_instruments()
        type(self)._current = self

    @classmethod
    def _register_instruments(cls) -> None:
        if cls._registered:
            return
        cls._registered = True
        meter.create_observable_gauge(
            name="plain.jobs.worker.processes",
            callbacks=[cls._gauge_worker_processes],
            unit="{process}",
            description="OS processes spawned by this worker.",
        )
        meter.create_observable_gauge(
            name="plain.jobs.queue.depth",
            callbacks=[cls._gauge_queue_depth],
            unit="{job}",
            description="Pending JobRequests ready to run, per queue.",
        )
        meter.create_observable_gauge(
            name="plain.jobs.queue.oldest.age",
            callbacks=[cls._gauge_queue_oldest_age],
            unit="s",
            description="Age of the oldest ready-to-run JobRequest, per queue.",
        )
        meter.create_observable_gauge(
            name="plain.jobs.queue.scheduled",
            callbacks=[cls._gauge_queue_scheduled],
            unit="{job}",
            description="JobRequests with start_at in the future, per queue.",
        )
        meter.create_observable_gauge(
            name="plain.jobs.running",
            callbacks=[cls._gauge_running],
            unit="{job}",
            description="JobProcess rows currently running, per queue.",
        )
        meter.create_observable_gauge(
            name="plain.jobs.workers",
            callbacks=[cls._gauge_workers],
            unit="{worker}",
            description=(
                "WorkerHeartbeat row count, split by liveness state "
                "(active=within JOBS_HEARTBEAT_TIMEOUT, stale=past it)."
            ),
        )

    # --- Callbacks ----------------------------------------------------------

    # Each callback snapshots `cls._current` to a local — `deactivate()` can
    # null the class var on another thread mid-callback (PeriodicExporting
    # MetricReader runs callbacks off the main thread).

    @classmethod
    def _gauge_worker_processes(cls, options: CallbackOptions) -> Iterable[Observation]:
        active = cls._current
        if active is None:
            return []
        try:
            n = len(active.worker.executor._processes)
        except (AttributeError, TypeError):
            # Pool may be mid-shutdown; report 0 rather than crashing the export.
            n = 0
        return [Observation(n)]

    @classmethod
    def _gauge_queue_depth(cls, options: CallbackOptions) -> Iterable[Observation]:
        active = cls._current
        if active is None:
            return []
        # Lazy import - see Worker._worker_process_initializer() comment for why.
        from .models import JobRequest

        return _count_per_queue(JobRequest.query.ready_to_run(), active.worker.queues)

    @classmethod
    def _gauge_queue_oldest_age(cls, options: CallbackOptions) -> Iterable[Observation]:
        active = cls._current
        if active is None:
            return []
        from .models import JobRequest

        queues = active.worker.queues
        rows = (
            JobRequest.query.ready_to_run()
            .filter(queue__in=queues)
            .values("queue")
            .annotate(oldest=Min("created_at"))
        )
        now = timezone.now()
        # `max(0, ...)` defends against Python/Postgres clock skew producing
        # a negative age. Empty queues fall through to 0.0 below.
        ages = {
            row["queue"]: max(0.0, (now - row["oldest"]).total_seconds())
            for row in rows
            if row["oldest"] is not None
        }
        return [
            Observation(ages.get(q, 0.0), {MESSAGING_DESTINATION_NAME: q})
            for q in queues
        ]

    @classmethod
    def _gauge_queue_scheduled(cls, options: CallbackOptions) -> Iterable[Observation]:
        active = cls._current
        if active is None:
            return []
        from .models import JobRequest

        return _count_per_queue(JobRequest.query.scheduled(), active.worker.queues)

    @classmethod
    def _gauge_running(cls, options: CallbackOptions) -> Iterable[Observation]:
        active = cls._current
        if active is None:
            return []
        from .models import JobProcess

        return _count_per_queue(JobProcess.query.running(), active.worker.queues)

    # The worker-liveness gauge observes the global WorkerHeartbeat table and
    # doesn't need a calling Worker — emit unconditionally so dashboards keep
    # reporting even during a full worker drain. One snapshot of the cutoff
    # is shared across both observations so a row landing exactly at the
    # boundary can't be counted in both states (or neither).
    @classmethod
    def _gauge_workers(cls, options: CallbackOptions) -> Iterable[Observation]:
        from .models import WorkerHeartbeat, heartbeat_cutoff

        cutoff = heartbeat_cutoff()
        counts = WorkerHeartbeat.query.aggregate(
            active=Count("id", filter=Q(last_heartbeat_at__gte=cutoff)),
            stale=Count("id", filter=Q(last_heartbeat_at__lt=cutoff)),
        )
        return [
            Observation(counts["active"], {PLAIN_JOBS_WORKER_STATE: "active"}),
            Observation(counts["stale"], {PLAIN_JOBS_WORKER_STATE: "stale"}),
        ]


def _count_per_queue(queryset: Any, queues: list[str]) -> list[Observation]:
    rows = queryset.filter(queue__in=queues).values("queue").annotate(c=Count("*"))
    counts = {row["queue"]: row["c"] for row in rows}
    return [
        Observation(counts.get(q, 0), {MESSAGING_DESTINATION_NAME: q}) for q in queues
    ]
