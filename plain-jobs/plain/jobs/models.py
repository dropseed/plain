from __future__ import annotations

import datetime
import time
import traceback
from typing import TYPE_CHECKING, Any, ClassVar, Self
from uuid import UUID

from opentelemetry.semconv._incubating.attributes.messaging_attributes import (
    MESSAGING_CONSUMER_GROUP_NAME,
    MESSAGING_MESSAGE_ID,
    MESSAGING_OPERATION_NAME,
)
from opentelemetry.trace import Link, SpanContext, SpanKind, TraceFlags

from plain import postgres
from plain.logs import get_framework_logger
from plain.postgres import Field, transaction, types
from plain.postgres.expressions import F
from plain.runtime import settings
from plain.utils import timezone

from .exceptions import DeferJob
from .otel import (
    operation_duration_histogram,
    process_metric_attributes,
    queue_wait_duration_histogram,
    record_consumed,
    record_span_error,
    tracer,
)
from .registry import jobs_registry

if TYPE_CHECKING:
    from .jobs import Job

__all__ = [
    "JobRequest",
    "JobProcess",
    "JobResult",
    "JobResultStatuses",
    "WorkerHeartbeat",
]

logger = get_framework_logger()


class JobRequestQuerySet(postgres.QuerySet["JobRequest"]):
    def ready_to_run(self) -> Self:
        """JobRequests with no scheduling constraint or whose `start_at` is past."""
        return self.filter(
            postgres.Q(start_at__isnull=True) | postgres.Q(start_at__lte=timezone.now())
        )

    def scheduled(self) -> Self:
        """JobRequests scheduled to start in the future."""
        return self.filter(start_at__gt=timezone.now())


@postgres.register_model
class JobRequest(postgres.Model):
    """
    Keep all pending job requests in a single table.
    """

    created_at: Field[datetime.datetime] = types.DateTimeField(create_now=True)
    uuid: Field[UUID] = types.UUIDField(generate=True)

    job_class: Field[str] = types.TextField(max_length=255)
    parameters: Field[dict[str, Any] | None] = types.JSONField(
        required=False, allow_null=True, default=None
    )
    priority: Field[int] = types.SmallIntegerField(default=0)
    source: Field[str] = types.TextField(required=False)
    queue: Field[str] = types.TextField(default="default", max_length=255)

    retries: Field[int] = types.SmallIntegerField(default=0)
    retry_attempt: Field[int] = types.SmallIntegerField(default=0)

    concurrency_key: Field[str] = types.TextField(max_length=255, required=False)

    start_at: Field[datetime.datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )

    # OpenTelemetry trace context
    trace_id: Field[str | None] = types.TextField(
        max_length=34, required=False, allow_null=True, default=None
    )
    span_id: Field[str | None] = types.TextField(
        max_length=18, required=False, allow_null=True, default=None
    )

    # expires_at = postgres.DateTimeField(required=False, allow_null=True)

    query: ClassVar[JobRequestQuerySet] = JobRequestQuerySet()

    model_options = postgres.Options(
        ordering=["-priority", "-created_at"],
        indexes=[
            postgres.Index(
                name="plainjobs_jobrequest_priority_idx", fields=["priority"]
            ),
            postgres.Index(
                name="plainjobs_jobrequest_created_at_idx", fields=["created_at"]
            ),
            postgres.Index(name="plainjobs_jobrequest_queue_idx", fields=["queue"]),
            postgres.Index(
                name="plainjobs_jobrequest_start_at_idx", fields=["start_at"]
            ),
            postgres.Index(
                name="plainjobs_jobrequest_concurrency_key_idx",
                fields=["concurrency_key"],
            ),
            # Used for job grouping queries
            postgres.Index(
                name="job_request_concurrency_key",
                fields=["job_class", "concurrency_key"],
            ),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["uuid"], name="plainjobs_jobrequest_unique_uuid"
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.job_class} [{self.uuid}]"

    def convert_to_job_process(self, *, worker_id: UUID) -> JobProcess:
        """
        JobRequests are the pending jobs that are waiting to be executed.
        We immediately convert them to JobProcess when they are picked up.

        worker_id stamps ownership: rescue_stale_workers uses it to find
        which jobs belonged to a worker whose heartbeat went stale. Required —
        every JobProcess has an owning worker, and the NOT NULL column
        constraint is what stops pre-heartbeat workers from inserting
        unrescuable rows during a rolling upgrade.
        """
        with transaction.atomic():
            result = JobProcess.query.create(
                job_request_uuid=self.uuid,
                requested_at=self.created_at,
                job_class=self.job_class,
                parameters=self.parameters,
                priority=self.priority,
                source=self.source,
                queue=self.queue,
                retries=self.retries,
                retry_attempt=self.retry_attempt,
                concurrency_key=self.concurrency_key,
                trace_id=self.trace_id,
                span_id=self.span_id,
                worker_id=worker_id,
            )

            # Delete the pending JobRequest now
            self.delete()

        return result


class JobQuerySet(postgres.QuerySet["JobProcess"]):
    def running(self) -> Self:
        return self.filter(started_at__isnull=False)

    def waiting(self) -> Self:
        return self.filter(started_at__isnull=True)


@postgres.register_model
class JobProcess(postgres.Model):
    """
    All active jobs are stored in this table.
    """

    uuid: Field[UUID] = types.UUIDField(generate=True)
    created_at: Field[datetime.datetime] = types.DateTimeField(create_now=True)
    started_at: Field[datetime.datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )

    # From the JobRequest
    job_request_uuid: Field[UUID] = types.UUIDField()
    requested_at: Field[datetime.datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    job_class: Field[str] = types.TextField(max_length=255)
    parameters: Field[dict[str, Any] | None] = types.JSONField(
        required=False, allow_null=True, default=None
    )
    priority: Field[int] = types.SmallIntegerField(default=0)
    source: Field[str] = types.TextField(required=False)
    queue: Field[str] = types.TextField(default="default", max_length=255)
    retries: Field[int] = types.SmallIntegerField(default=0)
    retry_attempt: Field[int] = types.SmallIntegerField(default=0)
    concurrency_key: Field[str] = types.TextField(max_length=255, required=False)

    # OpenTelemetry trace context
    trace_id: Field[str | None] = types.TextField(
        max_length=34, required=False, allow_null=True, default=None
    )
    span_id: Field[str | None] = types.TextField(
        max_length=18, required=False, allow_null=True, default=None
    )

    worker_id: Field[UUID] = types.UUIDField()

    query: ClassVar[JobQuerySet] = JobQuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(
                name="plainjobs_jobprocess_created_at_idx", fields=["created_at"]
            ),
            postgres.Index(name="plainjobs_jobprocess_queue_idx", fields=["queue"]),
            postgres.Index(
                name="plainjobs_jobprocess_concurrency_key_idx",
                fields=["concurrency_key"],
            ),
            postgres.Index(
                name="plainjobs_jobprocess_started_at_idx", fields=["started_at"]
            ),
            postgres.Index(
                name="plainjobs_jobprocess_job_request_uuid_idx",
                fields=["job_request_uuid"],
            ),
            postgres.Index(
                name="plainjobs_jobprocess_worker_id_idx", fields=["worker_id"]
            ),
            # Used for job grouping queries
            postgres.Index(
                name="job_concurrency_key",
                fields=["job_class", "concurrency_key"],
            ),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["uuid"], name="plainjobs_job_unique_uuid"
            ),
        ],
    )

    def revert_to_job_request(self) -> JobRequest:
        """Undo convert_to_job_process — put the job back in the request queue."""
        with transaction.atomic():
            job_request = JobRequest.query.create(
                uuid=self.job_request_uuid,
                job_class=self.job_class,
                parameters=self.parameters,
                priority=self.priority,
                source=self.source,
                queue=self.queue,
                retries=self.retries,
                retry_attempt=self.retry_attempt,
                concurrency_key=self.concurrency_key,
                trace_id=self.trace_id,
                span_id=self.span_id,
            )
            self.delete()
        return job_request

    def run(self) -> JobResult:
        links = []
        if self.trace_id and self.span_id:
            try:
                links.append(
                    Link(
                        SpanContext(
                            trace_id=int(self.trace_id, 16),
                            span_id=int(self.span_id, 16),
                            is_remote=True,
                            trace_flags=TraceFlags(TraceFlags.SAMPLED),
                        )
                    )
                )
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid trace context for job",
                    extra={"job_uuid": self.uuid},
                )

        metric_attributes: dict[str, Any] = process_metric_attributes(
            self.queue, self.job_class
        )
        start_time = time.perf_counter()
        try:
            with tracer.start_as_current_span(
                f"process {self.queue}",
                kind=SpanKind.CONSUMER,
                attributes={
                    **metric_attributes,
                    MESSAGING_OPERATION_NAME: "process",
                    MESSAGING_MESSAGE_ID: str(self.uuid),
                    MESSAGING_CONSUMER_GROUP_NAME: self.queue,
                },
                links=links,
            ) as span:
                # This is how we know it has been picked up.
                # Keep `started_at` as a local: reading `self.started_at` back
                # through the descriptor types as `datetime | None` (the field
                # is `allow_null=True`), which doesn't subtract cleanly below.
                started_at = timezone.now()
                self.started_at = started_at
                self.update(fields=["started_at"])

                if self.requested_at:
                    queue_wait = (started_at - self.requested_at).total_seconds()
                    queue_wait_duration_histogram.record(queue_wait, metric_attributes)

                try:
                    job = jobs_registry.load_job(self.job_class, self.parameters)
                    job.job_process = self

                    try:
                        job.run()
                    except DeferJob as e:
                        # Job deferred - not an error, log at INFO level
                        logger.info(
                            "Job deferred",
                            extra={
                                "delay": e.delay,
                                "increment_retries": e.increment_retries,
                                "job_class": self.job_class,
                                "job_process_uuid": self.uuid,
                            },
                        )
                        result = self.defer(job=job, defer_exception=e)
                        if result.retry_job_request_uuid is None:
                            # Re-enqueue was blocked by should_enqueue() —
                            # either the default uniqueness rule (a peer
                            # exists) or a user override (rate limit, custom
                            # rule). Same treatment as the initial-enqueue
                            # path's `job.enqueue.skipped`: not an error,
                            # just visibility on the consumer span.
                            span.set_attribute("plain.jobs.defer.skipped", True)
                        return result

                    return self.convert_to_result(status=JobResultStatuses.SUCCESSFUL)

                except Exception as e:
                    # Note: if a rescuer already wrote JobResult(LOST) for this
                    # row (heartbeat went stale during a long job, then the job
                    # actually finished), the convert_to_result below trips the
                    # unique constraint on job_process_uuid and produces a
                    # second log line. Rare; correct outcome; not worth
                    # pre-checking on every successful job.
                    logger.exception(e)
                    error_type = record_span_error(span, e, metric_attributes)
                    return self.convert_to_result(
                        status=JobResultStatuses.ERRORED,
                        error="".join(traceback.format_tb(e.__traceback__)),
                        error_type=error_type,
                    )
        finally:
            duration = time.perf_counter() - start_time
            operation_duration_histogram.record(duration, metric_attributes)

    def defer(self, *, job: Job, defer_exception: DeferJob) -> JobResult:
        """Defer this job by re-enqueueing it for later execution.

        Atomically deletes the JobProcess, re-enqueues the job, and creates
        a JobResult. The concurrency slot is released before re-enqueue so
        the new request's own `should_enqueue()` check can pass.

        If `should_enqueue()` blocks the re-enqueue, the framework honors
        that signal — same convention as `run_in_worker()` and `retry_job()`,
        which both return `None` silently in the same situation. The
        JobResult is still `DEFERRED` but `retry_job_request_uuid` is
        `None`, the error message records that the re-enqueue was skipped,
        and the caller stamps `plain.jobs.defer.skipped=True` on the
        consumer span so this case is queryable in APM without surfacing
        as an exception.
        """
        # Calculate new retry_attempt based on increment_retries
        retry_attempt = (
            self.retry_attempt + 1
            if defer_exception.increment_retries
            else self.retry_attempt
        )

        with transaction.atomic():
            # 1. Save JobProcess state and delete (releases concurrency slot)
            job_process_uuid = self.uuid
            job_request_uuid = self.job_request_uuid
            requested_at = self.requested_at
            started_at = self.started_at
            self.delete()

            # 2. Re-enqueue job (concurrency check can now pass)
            new_job_request = job.run_in_worker(
                queue=self.queue,
                delay=defer_exception.delay,
                priority=self.priority,
                retries=self.retries,
                retry_attempt=retry_attempt,
                concurrency_key=self.concurrency_key,
            )

            if new_job_request is None:
                error = (
                    f"Deferred for {defer_exception.delay} seconds "
                    f"(re-enqueue skipped: should_enqueue() returned False "
                    f"for concurrency_key '{self.concurrency_key}')"
                )
                retry_job_request_uuid = None
            else:
                error = f"Deferred for {defer_exception.delay} seconds"
                retry_job_request_uuid = new_job_request.uuid

            # 3. Create JobResult (linking to new request if one was created)
            result = JobResult.query.create(
                ended_at=timezone.now(),
                error=error,
                status=JobResultStatuses.DEFERRED,
                retry_job_request_uuid=retry_job_request_uuid,
                # From the JobProcess
                job_process_uuid=job_process_uuid,
                started_at=started_at,
                # From the JobRequest
                job_request_uuid=job_request_uuid,
                requested_at=requested_at,
                job_class=self.job_class,
                parameters=self.parameters,
                priority=self.priority,
                source=self.source,
                queue=self.queue,
                retries=self.retries,
                retry_attempt=self.retry_attempt,
                concurrency_key=self.concurrency_key,
                trace_id=self.trace_id,
                span_id=self.span_id,
            )

        # Counter ticks for the DEFERRED outcome too — defer() bypasses
        # convert_to_result, so without this the deferred path would not
        # show up in the consumed counter.
        record_consumed(result)
        return result

    def convert_to_result(
        self,
        *,
        status: str,
        error: str = "",
        error_type: str | None = None,
        fire_hook: bool = True,
    ) -> JobResult:
        """
        Convert this JobProcess to a JobResult.

        error_type, when supplied, is the OTel-style exception name (matching
        the spec's `error.type` attribute). It rides along to the consumed
        counter so dashboards can group ERRORED jobs by exception class. Only
        the live exception-driven paths supply it — rescue (LOST) and direct
        cancellations have no exception object to derive it from.

        fire_hook controls whether on_aborted dispatches synchronously. The
        rescue path passes fire_hook=False so it can dispatch hooks AFTER its
        outer transaction commits — otherwise a hook DB error would mark the
        connection for rollback even though dispatch_aborted_hook catches the
        exception, poisoning the rescue commit.
        """
        with transaction.atomic():
            result = JobResult.query.create(
                ended_at=timezone.now(),
                error=error,
                status=status,
                # From the JobProcess
                job_process_uuid=self.uuid,
                started_at=self.started_at,
                # From the JobRequest
                job_request_uuid=self.job_request_uuid,
                requested_at=self.requested_at,
                job_class=self.job_class,
                parameters=self.parameters,
                priority=self.priority,
                source=self.source,
                queue=self.queue,
                retries=self.retries,
                retry_attempt=self.retry_attempt,
                concurrency_key=self.concurrency_key,
                trace_id=self.trace_id,
                span_id=self.span_id,
            )

            # Delete the JobProcess now
            self.delete()

        # Counter ticks for every terminal status — the live SUCCESSFUL/ERRORED
        # paths plus the LOST/CANCELLED paths that don't flow through
        # JobProcess.run()'s finally. The outcome attribute lets dashboards
        # split throughput by final status; error_type is forwarded for ERRORED
        # jobs caught by the live path.
        record_consumed(result, error_type=error_type)

        # Fire Job.on_aborted outside the atomic block so a raise in user code
        # can't roll back the framework's bookkeeping. Only for terminal
        # statuses run() couldn't observe.
        if fire_hook and status in (
            JobResultStatuses.LOST,
            JobResultStatuses.CANCELLED,
        ):
            result.dispatch_aborted_hook()

        return result

    def as_json(self) -> dict[str, str | int | dict | None]:
        """A JSON-compatible representation to make it easier to reference in Sentry or logging"""
        return {
            "uuid": str(self.uuid),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "job_request_uuid": str(self.job_request_uuid),
            "job_class": self.job_class,
            "parameters": self.parameters,
            "priority": self.priority,
            "source": self.source,
            "queue": self.queue,
            "retries": self.retries,
            "retry_attempt": self.retry_attempt,
            "concurrency_key": self.concurrency_key,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


class JobResultQuerySet(postgres.QuerySet["JobResult"]):
    def successful(self) -> Self:
        return self.filter(status=JobResultStatuses.SUCCESSFUL)

    def cancelled(self) -> Self:
        return self.filter(status=JobResultStatuses.CANCELLED)

    def lost(self) -> Self:
        return self.filter(status=JobResultStatuses.LOST)

    def errored(self) -> Self:
        return self.filter(status=JobResultStatuses.ERRORED)

    def retried(self) -> Self:
        return self.filter(
            postgres.Q(retry_job_request_uuid__isnull=False)
            | postgres.Q(retry_attempt__gt=0)
        )

    def failed(self) -> Self:
        return self.filter(
            status__in=[
                JobResultStatuses.ERRORED,
                JobResultStatuses.LOST,
                JobResultStatuses.CANCELLED,
            ]
        )

    def retryable(self) -> Self:
        return self.failed().filter(
            retry_job_request_uuid__isnull=True,
            retries__gt=0,
            retry_attempt__lt=F("retries"),
        )

    def retry_failed_jobs(self) -> None:
        for result in self.retryable():
            try:
                result.retry_job()
            except Exception:
                # If something went wrong (like a job class being deleted)
                # then we immediately increment the retry_attempt on the existing obj
                # so it won't retry forever.
                logger.exception(
                    "Failed to retry job, incrementing retry_attempt",
                    extra={"result": str(result)},
                )
                result.retry_attempt += 1
                result.update(fields=["retry_attempt"])


class JobResultStatuses(postgres.TextChoices):
    SUCCESSFUL = "SUCCESSFUL", "Successful"
    ERRORED = "ERRORED", "Errored"  # Threw an error
    CANCELLED = "CANCELLED", "Cancelled"  # Interrupted by shutdown/deploy
    DEFERRED = "DEFERRED", "Deferred"  # Intentionally rescheduled (will run again)
    LOST = (
        "LOST",
        "Lost",
    )  # Either process lost, lost in transit, or otherwise never finished


@postgres.register_model
class JobResult(postgres.Model):
    """
    All in-process and completed jobs are stored in this table.
    """

    uuid: Field[UUID] = types.UUIDField(generate=True)
    created_at: Field[datetime.datetime] = types.DateTimeField(create_now=True)

    # From the Job
    job_process_uuid: Field[UUID] = types.UUIDField()
    started_at: Field[datetime.datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    ended_at: Field[datetime.datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    error: Field[str] = types.TextField(required=False)
    status: Field[str] = types.TextField(
        max_length=20,
        choices=JobResultStatuses.choices,
    )

    # From the JobRequest
    job_request_uuid: Field[UUID] = types.UUIDField()
    requested_at: Field[datetime.datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    job_class: Field[str] = types.TextField(max_length=255)
    parameters: Field[dict[str, Any] | None] = types.JSONField(
        required=False, allow_null=True, default=None
    )
    priority: Field[int] = types.SmallIntegerField(default=0)
    source: Field[str] = types.TextField(required=False)
    queue: Field[str] = types.TextField(default="default", max_length=255)
    retries: Field[int] = types.SmallIntegerField(default=0)
    retry_attempt: Field[int] = types.SmallIntegerField(default=0)
    concurrency_key: Field[str] = types.TextField(max_length=255, required=False)

    # Retries
    retry_job_request_uuid: Field[UUID | None] = types.UUIDField(
        required=False, allow_null=True, default=None
    )

    # OpenTelemetry trace context
    trace_id: Field[str | None] = types.TextField(
        max_length=34, required=False, allow_null=True, default=None
    )
    span_id: Field[str | None] = types.TextField(
        max_length=18, required=False, allow_null=True, default=None
    )

    query: ClassVar[JobResultQuerySet] = JobResultQuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(
                name="plainjobs_jobresult_created_at_idx", fields=["created_at"]
            ),
            postgres.Index(name="plainjobs_jobresult_status_idx", fields=["status"]),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["uuid"], name="plainjobs_jobresult_unique_uuid"
            ),
            # One JobProcess produces exactly one JobResult. Guards the
            # rescue-vs-late-finish race: if our heartbeat goes stale during a
            # DB outage, a peer rescuer creates JobResult(LOST) for our
            # JobProcess. When our subprocess eventually finishes and calls
            # convert_to_result on the now-deleted JobProcess, the second
            # insert hits this constraint and is swallowed by process_job's
            # outer except — instead of silently producing two divergent
            # results for the same run.
            postgres.UniqueConstraint(
                fields=["job_process_uuid"],
                name="plainjobs_jobresult_unique_job_process_uuid",
            ),
        ],
    )

    def dispatch_aborted_hook(self) -> None:
        """
        Load the Job class and call its on_aborted hook with this result.

        Errors loading the class or running the hook are logged but suppressed
        so JobProcess → JobResult bookkeeping is never blocked by user code or
        stale registrations.
        """
        try:
            job = jobs_registry.load_job(self.job_class, self.parameters)
        except Exception:
            logger.exception(
                "Failed to load job for on_aborted hook",
                extra={"job_class": self.job_class},
            )
            return

        try:
            job.on_aborted(self)
        except Exception:
            logger.exception(
                "Job.on_aborted raised",
                extra={"job_class": self.job_class},
            )

    def retry_job(self, delay: int | None = None) -> JobRequest | None:
        retry_attempt = self.retry_attempt + 1
        job = jobs_registry.load_job(self.job_class, self.parameters)

        if delay is None:
            retry_delay = job.calculate_retry_delay(retry_attempt)
        else:
            retry_delay = delay

        with transaction.atomic():
            result = job.run_in_worker(
                # Pass most of what we know through so it stays consistent
                queue=self.queue,
                delay=retry_delay,
                priority=self.priority,
                retries=self.retries,
                retry_attempt=retry_attempt,
                concurrency_key=self.concurrency_key,
            )
            if result:
                self.retry_job_request_uuid = result.uuid
                self.update(fields=["retry_job_request_uuid"])
                return result

        return None


@postgres.register_model
class WorkerHeartbeat(postgres.Model):
    """
    A live registration row written by each worker process while it's running.

    Workers create a row at startup, bump `last_heartbeat_at` periodically, and
    delete it on clean shutdown. `rescue_stale_workers` finds rows whose
    heartbeat is older than `JOBS_HEARTBEAT_TIMEOUT` and rescues their
    in-flight jobs.
    """

    worker_id: Field[UUID] = types.UUIDField()
    hostname: Field[str] = types.TextField(max_length=255)
    pid: Field[int] = types.IntegerField()
    queues: Field[list[str]] = types.JSONField()
    started_at: Field[datetime.datetime] = types.DateTimeField(create_now=True)
    last_heartbeat_at: Field[datetime.datetime] = types.DateTimeField()

    model_options = postgres.Options(
        ordering=["-last_heartbeat_at"],
        indexes=[
            postgres.Index(
                name="plainjobs_workerheartbeat_last_heartbeat_at_idx",
                fields=["last_heartbeat_at"],
            ),
        ],
        constraints=[
            # The unique constraint provides the worker_id lookup index.
            postgres.UniqueConstraint(
                fields=["worker_id"],
                name="plainjobs_workerheartbeat_unique_worker_id",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"WorkerHeartbeat({self.worker_id} on {self.hostname}:{self.pid})"


def heartbeat_cutoff() -> datetime.datetime:
    """The timestamp before which a WorkerHeartbeat is considered stale.

    Single source of truth — rescue, admin display, and OTel gauges all
    consult this so they agree on which workers are alive.
    """
    return timezone.now() - datetime.timedelta(seconds=settings.JOBS_HEARTBEAT_TIMEOUT)


def rescue_stale_workers() -> list[JobResult]:
    """
    Convert in-flight JobProcess rows from dead workers to JobResult(LOST).

    A worker is dead when its WorkerHeartbeat is older than
    JOBS_HEARTBEAT_TIMEOUT. Detection is heartbeat-based, not time-based, so
    a long-running legitimate job is safe as long as its worker keeps
    heartbeating.

    Returns the JobResults whose on_aborted hook still needs to fire. The
    caller dispatches them, interleaving heartbeat ticks if needed — a slow
    or large batch of hooks would otherwise starve the calling worker's
    heartbeat and trigger false-positive rescue from a peer.

    This is a free function (not a queryset method) because rescue is
    inherently global: filtering would let one rescuer claim a dead heartbeat
    without converting all of that worker's jobs, stranding the rest forever.
    """
    cutoff = heartbeat_cutoff()
    dead_workers = WorkerHeartbeat.query.filter(last_heartbeat_at__lt=cutoff)

    pending_hooks: list[JobResult] = []
    for worker in dead_workers:
        # Per-worker rescue is atomic: the heartbeat delete (claim) and every
        # JobProcess→JobResult conversion either all commit, or all roll
        # back. Without this, a mid-loop failure would leave the heartbeat
        # deleted but some JobProcesses still stamped with the dead worker_id
        # — stranded forever with no heartbeat to match.
        #
        # on_aborted hooks are deferred: dispatching them inside the atomic
        # block would let a hook's DB error mark the connection for rollback
        # (even though dispatch_aborted_hook swallows the exception),
        # aborting the rescue commit.
        worker_hooks: list[JobResult] = []
        try:
            with transaction.atomic():
                # Atomic claim. If another rescuer also saw this dead
                # heartbeat, only one of us deletes a row. The loser sees 0
                # affected and skips.
                claimed = WorkerHeartbeat.query.filter(
                    worker_id=worker.worker_id,
                    last_heartbeat_at__lt=cutoff,
                ).delete()
                if not claimed:
                    continue

                # list() materializes the queryset before the loop body
                # starts deleting rows, so iteration can't skip entries.
                for job in list(JobProcess.query.filter(worker_id=worker.worker_id)):
                    result = job.convert_to_result(
                        status=JobResultStatuses.LOST, fire_hook=False
                    )
                    worker_hooks.append(result)
        except Exception:
            # One dead worker's failure shouldn't abort rescue of others. The
            # next rescue tick will retry this worker (heartbeat was rolled
            # back, so it's still discoverable).
            logger.exception(
                "Failed to rescue jobs for dead worker",
                extra={"worker_id": str(worker.worker_id)},
            )
            continue

        # Rescue committed. Hand hooks back for the caller to dispatch.
        pending_hooks.extend(worker_hooks)

    return pending_hooks
