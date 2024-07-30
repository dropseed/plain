import datetime
import logging
import traceback
import uuid

from plain import models
from plain.models import transaction
from plain.runtime import settings
from plain.utils import timezone

from .jobs import load_job

logger = logging.getLogger("plain.worker")


class JobRequest(models.Model):
    """
    Keep all pending job requests in a single table.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    job_class = models.CharField(max_length=255, db_index=True)
    parameters = models.JSONField(blank=True, null=True)
    priority = models.IntegerField(default=0, db_index=True)
    source = models.TextField(blank=True)
    queue = models.CharField(default="default", max_length=255, db_index=True)

    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)

    unique_key = models.CharField(max_length=255, blank=True, db_index=True)

    start_at = models.DateTimeField(blank=True, null=True, db_index=True)

    # context
    # expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["priority", "-created_at"]
        indexes = [
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
                name="unique_job_class_unique_key",
            )
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


class Job(models.Model):
    """
    All active jobs are stored in this table.
    """

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(blank=True, null=True, db_index=True)

    # From the JobRequest
    job_request_uuid = models.UUIDField(db_index=True)
    job_class = models.CharField(max_length=255, db_index=True)
    parameters = models.JSONField(blank=True, null=True)
    priority = models.IntegerField(default=0, db_index=True)
    source = models.TextField(blank=True)
    queue = models.CharField(default="default", max_length=255, db_index=True)
    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)
    unique_key = models.CharField(max_length=255, blank=True, db_index=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Used to dedupe unique in-process jobs
            models.Index(
                name="job_class_unique_key", fields=["job_class", "unique_key"]
            ),
        ]

    def run(self):
        # This is how we know it has been picked up
        self.started_at = timezone.now()
        self.save(update_fields=["started_at"])

        try:
            job = load_job(self.job_class, self.parameters)
            job.run()
            status = JobResultStatuses.SUCCESSFUL
            error = ""
        except Exception as e:
            status = JobResultStatuses.ERRORED
            error = "".join(traceback.format_tb(e.__traceback__))
            logger.exception(e)

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
            result.retry_job()


class JobResultStatuses(models.TextChoices):
    SUCCESSFUL = "SUCCESSFUL", "Successful"
    ERRORED = "ERRORED", "Errored"  # Threw an error
    CANCELLED = "CANCELLED", "Cancelled"  # Cancelled (probably by deploy)
    LOST = (
        "LOST",
        "Lost",
    )  # Either process lost, lost in transit, or otherwise never finished


class JobResult(models.Model):
    """
    All in-process and completed jobs are stored in this table.
    """

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # From the Job
    job_uuid = models.UUIDField(db_index=True)
    started_at = models.DateTimeField(blank=True, null=True, db_index=True)
    ended_at = models.DateTimeField(blank=True, null=True, db_index=True)
    error = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=JobResultStatuses.choices,
        db_index=True,
    )

    # From the JobRequest
    job_request_uuid = models.UUIDField(db_index=True)
    job_class = models.CharField(max_length=255, db_index=True)
    parameters = models.JSONField(blank=True, null=True)
    priority = models.IntegerField(default=0, db_index=True)
    source = models.TextField(blank=True)
    queue = models.CharField(default="default", max_length=255, db_index=True)
    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)
    unique_key = models.CharField(max_length=255, blank=True, db_index=True)

    # Retries
    retry_job_request_uuid = models.UUIDField(blank=True, null=True)

    objects = JobResultQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def retry_job(self, delay: int | None = None):
        retry_attempt = self.retry_attempt + 1

        try:
            job = load_job(self.job_class, self.parameters)
            class_delay = job.get_retry_delay(retry_attempt)
        except Exception as e:
            # If this fails at all (loading model instance from str, class not existing, user code error)
            # then we just continue without a delay. The job request itself can handle the failure like normal.
            logger.exception(e)
            class_delay = None

        retry_delay = delay or class_delay

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

            # It's possible this could return a list of pending
            # jobs, so we need to check if we actually created a new job
            if isinstance(result, JobRequest):
                # We need to know the retry request for this result
                self.retry_job_request_uuid = result.uuid
                self.save(update_fields=["retry_job_request_uuid"])
            else:
                # What to do in this situation? Will continue to run the retry
                # logic until it successfully retries or it is deleted.
                pass

        return result
