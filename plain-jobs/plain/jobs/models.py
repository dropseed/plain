from __future__ import annotations

import datetime
import logging
import traceback
import uuid
from typing import TYPE_CHECKING, Self

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_NAMESPACE,
)
from opentelemetry.semconv._incubating.attributes.messaging_attributes import (
    MESSAGING_CONSUMER_GROUP_NAME,
    MESSAGING_DESTINATION_NAME,
    MESSAGING_MESSAGE_ID,
    MESSAGING_OPERATION_NAME,
    MESSAGING_OPERATION_TYPE,
    MESSAGING_SYSTEM,
    MessagingOperationTypeValues,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.trace import Link, SpanContext, SpanKind

from plain import models
from plain.models import transaction
from plain.models.expressions import F
from plain.runtime import settings
from plain.utils import timezone

from .exceptions import DeferError, DeferJob
from .registry import jobs_registry

if TYPE_CHECKING:
    from .jobs import Job

logger = logging.getLogger("plain.jobs")
tracer = trace.get_tracer("plain.jobs")


@models.register_model
class JobRequest(models.Model):
    """
    Keep all pending job requests in a single table.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    uuid = models.UUIDField(default=uuid.uuid4)

    job_class = models.CharField(max_length=255)
    parameters = models.JSONField(required=False, allow_null=True)
    priority = models.SmallIntegerField(default=0)
    source = models.TextField(required=False)
    queue = models.CharField(default="default", max_length=255)

    retries = models.SmallIntegerField(default=0)
    retry_attempt = models.SmallIntegerField(default=0)

    concurrency_key = models.CharField(max_length=255, required=False)

    start_at = models.DateTimeField(required=False, allow_null=True)

    # OpenTelemetry trace context
    trace_id = models.CharField(max_length=34, required=False, allow_null=True)
    span_id = models.CharField(max_length=18, required=False, allow_null=True)

    # expires_at = models.DateTimeField(required=False, allow_null=True)

    model_options = models.Options(
        ordering=["priority", "-created_at"],
        indexes=[
            models.Index(fields=["priority"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["start_at"]),
            models.Index(fields=["concurrency_key"]),
            models.Index(fields=["job_class"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["uuid"]),
            # Used for job grouping queries
            models.Index(
                name="job_request_concurrency_key",
                fields=["job_class", "concurrency_key"],
            ),
        ],
        constraints=[
            models.UniqueConstraint(
                fields=["uuid"], name="plainjobs_jobrequest_unique_uuid"
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.job_class} [{self.uuid}]"

    def convert_to_job_process(self) -> JobProcess:
        """
        JobRequests are the pending jobs that are waiting to be executed.
        We immediately convert them to JobProcess when they are picked up.
        """
        with transaction.atomic():
            result = JobProcess.query.create(
                job_request_uuid=self.uuid,
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

            # Delete the pending JobRequest now
            self.delete()

        return result


class JobQuerySet(models.QuerySet["JobProcess"]):
    def running(self) -> Self:
        return self.filter(started_at__isnull=False)

    def waiting(self) -> Self:
        return self.filter(started_at__isnull=True)

    def mark_lost_jobs(self) -> None:
        # Lost jobs are jobs that have been pending for too long,
        # and probably never going to get picked up by a worker process.
        # In theory we could save a timeout per-job and mark them timed-out more quickly,
        # but if they're still running, we can't actually send a signal to cancel it...
        now = timezone.now()
        cutoff = now - datetime.timedelta(seconds=settings.JOBS_TIMEOUT)
        lost_jobs = self.filter(
            created_at__lt=cutoff
        )  # Doesn't matter whether it started or not -- it shouldn't take this long.

        # Note that this will save it in the results,
        # but lost jobs are only retried if they have a retry!
        for job in lost_jobs:
            job.convert_to_result(status=JobResultStatuses.LOST)


@models.register_model
class JobProcess(models.Model):
    """
    All active jobs are stored in this table.
    """

    uuid = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(required=False, allow_null=True)

    # From the JobRequest
    job_request_uuid = models.UUIDField()
    job_class = models.CharField(max_length=255)
    parameters = models.JSONField(required=False, allow_null=True)
    priority = models.SmallIntegerField(default=0)
    source = models.TextField(required=False)
    queue = models.CharField(default="default", max_length=255)
    retries = models.SmallIntegerField(default=0)
    retry_attempt = models.SmallIntegerField(default=0)
    concurrency_key = models.CharField(max_length=255, required=False)

    # OpenTelemetry trace context
    trace_id = models.CharField(max_length=34, required=False, allow_null=True)
    span_id = models.CharField(max_length=18, required=False, allow_null=True)

    query = JobQuerySet()

    model_options = models.Options(
        ordering=["-created_at"],
        indexes=[
            models.Index(fields=["created_at"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["concurrency_key"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["job_class"]),
            models.Index(fields=["job_request_uuid"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["uuid"]),
            # Used for job grouping queries
            models.Index(
                name="job_concurrency_key",
                fields=["job_class", "concurrency_key"],
            ),
        ],
        constraints=[
            models.UniqueConstraint(fields=["uuid"], name="plainjobs_job_unique_uuid"),
        ],
    )

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
                        )
                    )
                )
            except (ValueError, TypeError):
                logger.warning("Invalid trace context for job %s", self.uuid)

        with (
            tracer.start_as_current_span(
                f"run {self.job_class}",
                kind=SpanKind.CONSUMER,
                attributes={
                    MESSAGING_SYSTEM: "plain.jobs",
                    MESSAGING_OPERATION_TYPE: MessagingOperationTypeValues.PROCESS.value,
                    MESSAGING_OPERATION_NAME: "run",
                    MESSAGING_MESSAGE_ID: str(self.uuid),
                    MESSAGING_DESTINATION_NAME: self.queue,
                    MESSAGING_CONSUMER_GROUP_NAME: self.queue,  # Workers consume from specific queues
                    CODE_NAMESPACE: self.job_class,
                },
                links=links,
            ) as span
        ):
            # This is how we know it has been picked up
            self.started_at = timezone.now()
            self.save(update_fields=["started_at"])

            try:
                job = jobs_registry.load_job(self.job_class, self.parameters)
                job.job_process = self

                try:
                    job.run()
                except DeferJob as e:
                    # Job deferred - not an error, log at INFO level
                    logger.info(
                        "Job deferred for %s seconds (increment_retries=%s): job_class=%s job_process_uuid=%s",
                        e.delay,
                        e.increment_retries,
                        self.job_class,
                        self.uuid,
                    )
                    span.set_attribute(ERROR_TYPE, "DeferJob")
                    span.set_status(trace.StatusCode.OK)  # Not an error
                    return self.defer(job=job, defer_exception=e)

                # Success case (only reached if no DeferJob was raised)
                span.set_status(trace.StatusCode.OK)
                return self.convert_to_result(status=JobResultStatuses.SUCCESSFUL)

            except Exception as e:
                logger.exception(e)
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.set_attribute(ERROR_TYPE, type(e).__name__)
                return self.convert_to_result(
                    status=JobResultStatuses.ERRORED,
                    error="".join(traceback.format_tb(e.__traceback__)),
                )

    def defer(self, *, job: Job, defer_exception: DeferJob) -> JobResult:
        """Defer this job by re-enqueueing it for later execution.

        Atomically deletes the JobProcess, re-enqueues the job, and creates
        a JobResult linking to the new request. This ensures the concurrency
        slot is released before attempting to re-enqueue.

        Raises:
            DeferError: If the job cannot be re-enqueued (e.g., due to concurrency limits).
                       The transaction will be rolled back and the JobProcess will remain.
        """
        # Calculate new retry_attempt based on increment_retries
        retry_attempt = (
            self.retry_attempt + 1
            if defer_exception.increment_retries
            else self.retry_attempt
        )

        with transaction.atomic():
            # 1. Save JobProcess UUID and delete (releases concurrency slot)
            job_process_uuid = self.uuid
            job_request_uuid = self.job_request_uuid
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

            # Check if re-enqueue failed
            if new_job_request is None:
                raise DeferError(
                    f"Failed to re-enqueue deferred job {self.job_class}: "
                    f"concurrency limit reached for key '{self.concurrency_key}'"
                )

            # 3. Create JobResult linking to new request
            result = JobResult.query.create(
                ended_at=timezone.now(),
                error=f"Deferred for {defer_exception.delay} seconds",
                status=JobResultStatuses.DEFERRED,
                retry_job_request_uuid=new_job_request.uuid,
                # From the JobProcess
                job_process_uuid=job_process_uuid,
                started_at=started_at,
                # From the JobRequest
                job_request_uuid=job_request_uuid,
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

            return result

    def convert_to_result(self, *, status: str, error: str = "") -> JobResult:
        """
        Convert this JobProcess to a JobResult.
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


class JobResultQuerySet(models.QuerySet["JobResult"]):
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
            models.Q(retry_job_request_uuid__isnull=False)
            | models.Q(retry_attempt__gt=0)
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
                    "Failed to retry job (incrementing retry_attempt): %s", result
                )
                result.retry_attempt += 1
                result.save(update_fields=["retry_attempt"])


class JobResultStatuses(models.TextChoices):
    SUCCESSFUL = "SUCCESSFUL", "Successful"
    ERRORED = "ERRORED", "Errored"  # Threw an error
    CANCELLED = "CANCELLED", "Cancelled"  # Interrupted by shutdown/deploy
    DEFERRED = "DEFERRED", "Deferred"  # Intentionally rescheduled (will run again)
    LOST = (
        "LOST",
        "Lost",
    )  # Either process lost, lost in transit, or otherwise never finished


@models.register_model
class JobResult(models.Model):
    """
    All in-process and completed jobs are stored in this table.
    """

    uuid = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)

    # From the Job
    job_process_uuid = models.UUIDField()
    started_at = models.DateTimeField(required=False, allow_null=True)
    ended_at = models.DateTimeField(required=False, allow_null=True)
    error = models.TextField(required=False)
    status = models.CharField(
        max_length=20,
        choices=JobResultStatuses.choices,
    )

    # From the JobRequest
    job_request_uuid = models.UUIDField()
    job_class = models.CharField(max_length=255)
    parameters = models.JSONField(required=False, allow_null=True)
    priority = models.SmallIntegerField(default=0)
    source = models.TextField(required=False)
    queue = models.CharField(default="default", max_length=255)
    retries = models.SmallIntegerField(default=0)
    retry_attempt = models.SmallIntegerField(default=0)
    concurrency_key = models.CharField(max_length=255, required=False)

    # Retries
    retry_job_request_uuid = models.UUIDField(required=False, allow_null=True)

    # OpenTelemetry trace context
    trace_id = models.CharField(max_length=34, required=False, allow_null=True)
    span_id = models.CharField(max_length=18, required=False, allow_null=True)

    query = JobResultQuerySet()

    model_options = models.Options(
        ordering=["-created_at"],
        indexes=[
            models.Index(fields=["created_at"]),
            models.Index(fields=["job_process_uuid"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["ended_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["job_request_uuid"]),
            models.Index(fields=["job_class"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["uuid"]),
        ],
        constraints=[
            models.UniqueConstraint(
                fields=["uuid"], name="plainjobs_jobresult_unique_uuid"
            ),
        ],
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
                self.save(update_fields=["retry_job_request_uuid"])
                return result

        return None
