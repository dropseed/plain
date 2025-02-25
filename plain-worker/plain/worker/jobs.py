import datetime
import inspect
import logging

from plain.models import IntegrityError
from plain.utils import timezone

from .registry import JobParameters, jobs_registry

logger = logging.getLogger(__name__)


class JobType(type):
    """
    Metaclass allows us to capture the original args/kwargs
    used to instantiate the job, so we can store them in the database
    when we schedule the job.
    """

    def __call__(self, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        instance._init_args = args
        instance._init_kwargs = kwargs
        return instance


class Job(metaclass=JobType):
    def run(self):
        raise NotImplementedError

    def run_in_worker(
        self,
        *,
        queue: str | None = None,
        delay: int | datetime.timedelta | datetime.datetime | None = None,
        priority: int | None = None,
        retries: int | None = None,
        retry_attempt: int = 0,
        unique_key: str | None = None,
    ):
        from .models import JobRequest

        try:
            # Try to automatically annotate the source of the job
            caller = inspect.stack()[1]
            source = f"{caller.filename}:{caller.lineno}"
        except (IndexError, AttributeError):
            source = ""

        parameters = JobParameters.to_json(self._init_args, self._init_kwargs)

        if queue is None:
            queue = self.get_queue()

        if priority is None:
            priority = self.get_priority()

        if retries is None:
            retries = self.get_retries()

        if delay is None:
            start_at = None
        elif isinstance(delay, int):
            start_at = timezone.now() + datetime.timedelta(seconds=delay)
        elif isinstance(delay, datetime.timedelta):
            start_at = timezone.now() + delay
        elif isinstance(delay, datetime.datetime):
            start_at = delay
        else:
            raise ValueError(f"Invalid delay: {delay}")

        if unique_key is None:
            unique_key = self.get_unique_key()

        if unique_key:
            # Only need to look at in progress jobs
            # if we also have a unique key.
            # Otherwise it's up to the user to use _in_progress()
            if running := self._in_progress(unique_key):
                return running

        try:
            job_request = JobRequest(
                job_class=jobs_registry.get_job_class_name(self.__class__),
                parameters=parameters,
                start_at=start_at,
                source=source,
                queue=queue,
                priority=priority,
                retries=retries,
                retry_attempt=retry_attempt,
                unique_key=unique_key,
            )
            job_request.save(
                clean_and_validate=False
            )  # So IntegrityError is raised on unique instead of potentially confusing ValidationError...
            return job_request
        except IntegrityError as e:
            logger.warning("Job already in progress: %s", e)
            # Try to return the _in_progress list again
            return self._in_progress(unique_key)

    def _in_progress(self, unique_key):
        """Get all JobRequests and Jobs that are currently in progress, regardless of queue."""
        from .models import Job, JobRequest

        job_class_name = jobs_registry.get_job_class_name(self.__class__)

        job_requests = JobRequest.objects.filter(
            job_class=job_class_name,
            unique_key=unique_key,
        )

        jobs = Job.objects.filter(
            job_class=job_class_name,
            unique_key=unique_key,
        )

        return list(job_requests) + list(jobs)

    def get_unique_key(self) -> str:
        """
        A unique key to prevent duplicate jobs from being queued.
        Enabled by returning a non-empty string.

        Note that this is not a "once and only once" guarantee, but rather
        an "at least once" guarantee. Jobs should still be idempotent in case
        multiple instances are queued in a race condition.
        """
        return ""

    def get_queue(self) -> str:
        return "default"

    def get_priority(self) -> int:
        return 0

    def get_retries(self) -> int:
        return 0

    def get_retry_delay(self, attempt: int) -> int:
        """
        Calcluate a delay in seconds before the next retry attempt.

        On the first retry, attempt will be 1.
        """
        return 0
