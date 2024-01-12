import datetime
import logging
import traceback
import uuid

from bolt.db import models, transaction
from bolt.utils import timezone

from .jobs import load_job

logger = logging.getLogger("bolt.jobs")


class JobRequestQuerySet(models.QuerySet):
    def next_up(self):
        return (
            self.select_for_update(skip_locked=True)
            .filter(
                models.Q(start_at__isnull=True) | models.Q(start_at__lte=timezone.now())
            )
            .order_by("priority", "-start_at", "-created_at")
            .first()
        )


class JobRequest(models.Model):
    """
    Keep all pending job requests in a single table.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    job_class = models.CharField(max_length=255, db_index=True)
    parameters = models.JSONField(blank=True, null=True)
    priority = models.IntegerField(default=0, db_index=True)
    source = models.TextField(blank=True)

    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)

    start_at = models.DateTimeField(blank=True, null=True, db_index=True)

    # context
    # expires_at = models.DateTimeField(blank=True, null=True)

    objects = JobRequestQuerySet.as_manager()

    class Meta:
        ordering = ["priority", "-created_at"]

    def __str__(self):
        return f"{self.job_class} [{self.uuid}]"

    def convert_to_result(self):
        """
        JobRequests are the pending jobs that are waiting to be executed.
        We immediately convert them to JobResults when they are picked up.
        """
        result = JobResult.objects.create(
            job_request_uuid=self.uuid,
            job_class=self.job_class,
            parameters=self.parameters,
            priority=self.priority,
            source=self.source,
            retries=self.retries,
            retry_attempt=self.retry_attempt,
        )

        # Delete the pending JobRequest now
        self.delete()

        return result


class JobResultQuerySet(models.QuerySet):
    def unknown(self):
        return self.filter(status=JobResultStatuses.UNKNOWN)

    def processing(self):
        return self.filter(status=JobResultStatuses.PROCESSING)

    def successful(self):
        return self.filter(status=JobResultStatuses.SUCCESSFUL)

    def lost(self):
        return self.filter(status=JobResultStatuses.LOST)

    def errored(self):
        return self.filter(status=JobResultStatuses.ERRORED)

    def retried(self):
        return self.filter(
            models.Q(retry_job_request_uuid__isnull=False)
            | models.Q(retry_attempt__gt=0)
        )

    def mark_lost_jobs(self):
        # Nothing should be pending after more than a 24 hrs... consider it lost
        # Downside to these is that they are mark lost pretty late?
        # In theory we could save a timeout per-job and mark them timed-out more quickly,
        # but if they're still running, we can't actually send a signal to cancel it...
        now = timezone.now()
        one_day_ago = now - datetime.timedelta(days=1)
        self.filter(
            status__in=[JobResultStatuses.PROCESSING, JobResultStatuses.UNKNOWN],
            created_at__lt=one_day_ago,
        ).update(status=JobResultStatuses.LOST, ended_at=now)

    def retry_failed_jobs(self):
        for result in self.filter(
            status__in=[JobResultStatuses.ERRORED, JobResultStatuses.LOST],
            retry_job_request_uuid__isnull=True,
            retries__gt=0,
            retry_attempt__lt=models.F("retries"),
        ):
            result.retry_job()


class JobResultStatuses(models.TextChoices):
    UNKNOWN = "", "Unknown"  # The initial state
    PROCESSING = "PROCESSING", "Processing"
    SUCCESSFUL = "SUCCESSFUL", "Successful"
    ERRORED = "ERRORED", "Errored"  # Threw an error
    LOST = (
        "LOST",
        "Lost",
    )  # Either process lost, lost in transit, or otherwise never finished


class JobResult(models.Model):
    """
    All in-process and completed jobs are stored in this table.
    """

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True, db_index=True)
    ended_at = models.DateTimeField(blank=True, null=True, db_index=True)
    error = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=JobResultStatuses.choices,
        blank=True,
        default=JobResultStatuses.UNKNOWN,
        db_index=True,
    )

    # From the JobRequest
    job_request_uuid = models.UUIDField(db_index=True)
    job_class = models.CharField(max_length=255, db_index=True)
    parameters = models.JSONField(blank=True, null=True)
    priority = models.IntegerField(default=0, db_index=True)
    source = models.TextField(blank=True)
    retries = models.IntegerField(default=0)
    retry_attempt = models.IntegerField(default=0)

    # Retries
    retry_job_request_uuid = models.UUIDField(blank=True, null=True)

    objects = JobResultQuerySet.as_manager()

    class Meta:
        ordering = ["-started_at"]

    def process_job(self):
        self.started_at = timezone.now()
        self.status = JobResultStatuses.PROCESSING
        self.save(update_fields=["started_at", "status"])

        try:
            job = load_job(self.job_class, self.parameters)
            job.run()
            self.status = JobResultStatuses.SUCCESSFUL
        except Exception as e:
            self.error = "".join(traceback.format_tb(e.__traceback__))
            self.status = JobResultStatuses.ERRORED
            logger.exception(e)

        self.ended_at = timezone.now()
        self.save(update_fields=["ended_at", "error", "status"])

    def retry_job(self, delay: int | None = None):
        retry_attempt = self.retry_attempt + 1
        job = load_job(self.job_class, self.parameters)

        if delay is not None:
            # A manual delay set when calling retry_job.
            # Use 0 to retry immediately.
            start_at = timezone.now() + datetime.timedelta(seconds=delay)
        elif class_delay := job.get_retry_delay(retry_attempt):
            # Delay based on job class
            start_at = timezone.now() + datetime.timedelta(seconds=class_delay)
        else:
            # No delay
            start_at = None

        with transaction.atomic():
            retry_request = JobRequest.objects.create(
                job_class=self.job_class,
                parameters=self.parameters,
                priority=self.priority,
                source=self.source,
                retries=self.retries,
                retry_attempt=retry_attempt,
                start_at=start_at,
            )

            # So we know this result was retried
            self.retry_job_request_uuid = retry_request.uuid
            self.save(update_fields=["retry_job_request_uuid"])

        return retry_request
