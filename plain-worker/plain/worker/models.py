import datetime
import logging
import traceback
import uuid

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
from plain.runtime import settings
from plain.utils import timezone

from .registry import jobs_registry

logger = logging.getLogger("plain.worker")
tracer = trace.get_tracer("plain.worker")


@models.register_model
class JobRequest(models.Model):
    """
    Keep all pending job requests in a single table.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    uuid = models.UUIDField(default=uuid.uuid4)

    job_class = models.CharField(max_length=255)
    parameters = models.JSONField(required=False, allow_null=True)
    priority = models.IntegerField(default=0)
    source = models.TextField(required=False)
    queue = models.CharField(default="default", max_length=255)

    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)

    unique_key = models.CharField(max_length=255, required=False)

    start_at = models.DateTimeField(required=False, allow_null=True)

    # OpenTelemetry trace context
    trace_id = models.CharField(max_length=34, required=False, allow_null=True)
    span_id = models.CharField(max_length=18, required=False, allow_null=True)

    # expires_at = models.DateTimeField(required=False, allow_null=True)

    class Meta:
        ordering = ["priority", "-created_at"]
        indexes = [
            models.Index(fields=["priority"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["start_at"]),
            models.Index(fields=["unique_key"]),
            models.Index(fields=["job_class"]),
            models.Index(fields=["trace_id"]),
            # Used to dedupe unique in-process jobs
            models.Index(
                name="job_request_class_unique_key", fields=["job_class", "unique_key"]
            ),
        ]
        # The job_class and unique_key should be unique at the db-level,
        # but only if unique_key is not ""
        constraints = [
            models.UniqueConstraint(
                fields=["job_class", "unique_key"],
                condition=models.Q(unique_key__gt="", retry_attempt=0),
                name="plainworker_jobrequest_unique_job_class_key",
            ),
            models.UniqueConstraint(
                fields=["uuid"], name="plainworker_jobrequest_unique_uuid"
            ),
        ]

    def __str__(self):
        return f"{self.job_class} [{self.uuid}]"

    def convert_to_job(self):
        """
        JobRequests are the pending jobs that are waiting to be executed.
        We immediately convert them to JobResults when they are picked up.
        """
        with transaction.atomic():
            result = Job.objects.create(
                job_request_uuid=self.uuid,
                job_class=self.job_class,
                parameters=self.parameters,
                priority=self.priority,
                source=self.source,
                queue=self.queue,
                retries=self.retries,
                retry_attempt=self.retry_attempt,
                unique_key=self.unique_key,
                trace_id=self.trace_id,
                span_id=self.span_id,
            )

            # Delete the pending JobRequest now
            self.delete()

        return result


class JobQuerySet(models.QuerySet):
    def running(self):
        return self.filter(started_at__isnull=False)

    def waiting(self):
        return self.filter(started_at__isnull=True)

    def mark_lost_jobs(self):
        # Lost jobs are jobs that have been pending for too long,
        # and probably never going to get picked up by a worker process.
        # In theory we could save a timeout per-job and mark them timed-out more quickly,
        # but if they're still running, we can't actually send a signal to cancel it...
        now = timezone.now()
        cutoff = now - datetime.timedelta(seconds=settings.WORKER_JOBS_LOST_AFTER)
        lost_jobs = self.filter(
            created_at__lt=cutoff
        )  # Doesn't matter whether it started or not -- it shouldn't take this long.

        # Note that this will save it in the results,
        # but lost jobs are only retried if they have a retry!
        for job in lost_jobs:
            job.convert_to_result(status=JobResultStatuses.LOST)


@models.register_model
class Job(models.Model):
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
    priority = models.IntegerField(default=0)
    source = models.TextField(required=False)
    queue = models.CharField(default="default", max_length=255)
    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)
    unique_key = models.CharField(max_length=255, required=False)

    # OpenTelemetry trace context
    trace_id = models.CharField(max_length=34, required=False, allow_null=True)
    span_id = models.CharField(max_length=18, required=False, allow_null=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["unique_key"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["job_class"]),
            models.Index(fields=["job_request_uuid"]),
            models.Index(fields=["trace_id"]),
            # Used to dedupe unique in-process jobs
            models.Index(
                name="job_class_unique_key", fields=["job_class", "unique_key"]
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["uuid"], name="plainworker_job_unique_uuid"
            ),
        ]

    def run(self):
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
                    MESSAGING_SYSTEM: "plain.worker",
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
                job.run()
                status = JobResultStatuses.SUCCESSFUL
                error = ""
                span.set_status(trace.StatusCode.OK)
            except Exception as e:
                status = JobResultStatuses.ERRORED
                error = "".join(traceback.format_tb(e.__traceback__))
                logger.exception(e)
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.set_attribute(ERROR_TYPE, type(e).__name__)

            return self.convert_to_result(status=status, error=error)

    def convert_to_result(self, *, status, error=""):
        """
        Convert this Job to a JobResult.
        """
        with transaction.atomic():
            result = JobResult.objects.create(
                ended_at=timezone.now(),
                error=error,
                status=status,
                # From the Job
                job_uuid=self.uuid,
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
                unique_key=self.unique_key,
                trace_id=self.trace_id,
                span_id=self.span_id,
            )

            # Delete the Job now
            self.delete()

        return result

    def as_json(self):
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
            "unique_key": self.unique_key,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


class JobResultQuerySet(models.QuerySet):
    def successful(self):
        return self.filter(status=JobResultStatuses.SUCCESSFUL)

    def cancelled(self):
        return self.filter(status=JobResultStatuses.CANCELLED)

    def lost(self):
        return self.filter(status=JobResultStatuses.LOST)

    def errored(self):
        return self.filter(status=JobResultStatuses.ERRORED)

    def retried(self):
        return self.filter(
            models.Q(retry_job_request_uuid__isnull=False)
            | models.Q(retry_attempt__gt=0)
        )

    def failed(self):
        return self.filter(
            status__in=[
                JobResultStatuses.ERRORED,
                JobResultStatuses.LOST,
                JobResultStatuses.CANCELLED,
            ]
        )

    def retryable(self):
        return self.failed().filter(
            retry_job_request_uuid__isnull=True,
            retries__gt=0,
            retry_attempt__lt=models.F("retries"),
        )

    def retry_failed_jobs(self):
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
    CANCELLED = "CANCELLED", "Cancelled"  # Cancelled (probably by deploy)
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
    job_uuid = models.UUIDField()
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
    priority = models.IntegerField(default=0)
    source = models.TextField(required=False)
    queue = models.CharField(default="default", max_length=255)
    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)
    unique_key = models.CharField(max_length=255, required=False)

    # Retries
    retry_job_request_uuid = models.UUIDField(required=False, allow_null=True)

    # OpenTelemetry trace context
    trace_id = models.CharField(max_length=34, required=False, allow_null=True)
    span_id = models.CharField(max_length=18, required=False, allow_null=True)

    objects = JobResultQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["job_uuid"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["ended_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["job_request_uuid"]),
            models.Index(fields=["job_class"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["trace_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["uuid"], name="plainworker_jobresult_unique_uuid"
            ),
        ]

    def retry_job(self, delay: int | None = None):
        retry_attempt = self.retry_attempt + 1
        job = jobs_registry.load_job(self.job_class, self.parameters)
        retry_delay = delay or job.get_retry_delay(retry_attempt)

        with transaction.atomic():
            result = job.run_in_worker(
                # Pass most of what we know through so it stays consistent
                queue=self.queue,
                delay=retry_delay,
                priority=self.priority,
                retries=self.retries,
                retry_attempt=retry_attempt,
                # Unique key could be passed also?
            )

            # TODO it is actually possible that result is a list
            # of pending jobs, which would need to be handled...
            # Right now it will throw an exception which could be caught by retry_failed_jobs.

            self.retry_job_request_uuid = result.uuid
            self.save(update_fields=["retry_job_request_uuid"])

        return result
