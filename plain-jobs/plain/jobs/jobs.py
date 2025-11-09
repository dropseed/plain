from __future__ import annotations

import datetime
import inspect
from abc import ABCMeta, abstractmethod
from contextlib import AbstractContextManager, nullcontext
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_FILEPATH,
    CODE_LINENO,
)
from opentelemetry.semconv._incubating.attributes.messaging_attributes import (
    MESSAGING_DESTINATION_NAME,
    MESSAGING_MESSAGE_ID,
    MESSAGING_OPERATION_NAME,
    MESSAGING_OPERATION_TYPE,
    MESSAGING_SYSTEM,
    MessagingOperationTypeValues,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.trace import SpanKind, format_span_id, format_trace_id

from plain import models
from plain.models import transaction
from plain.models.db import db_connection
from plain.utils import timezone

from .locks import postgres_advisory_lock
from .registry import JobParameters, jobs_registry

if TYPE_CHECKING:
    from .models import JobProcess, JobRequest


tracer = trace.get_tracer("plain.jobs")


class JobType(ABCMeta):
    """
    Metaclass allows us to capture the original args/kwargs
    used to instantiate the job, so we can store them in the database
    when we schedule the job.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Job:
        instance = super().__call__(*args, **kwargs)
        instance._init_args = args
        instance._init_kwargs = kwargs
        return instance


class Job(metaclass=JobType):
    # Set by JobProcess when the job is executed
    # Useful for jobs that need to query and exclude themselves
    job_process: JobProcess | None = None

    @abstractmethod
    def run(self) -> None:
        pass

    def run_in_worker(
        self,
        *,
        queue: str | None = None,
        delay: int | datetime.timedelta | datetime.datetime | None = None,
        priority: int | None = None,
        retries: int | None = None,
        retry_attempt: int = 0,
        concurrency_key: str | None = None,
    ) -> JobRequest | None:
        from .models import JobRequest

        job_class_name = jobs_registry.get_job_class_name(self.__class__)

        if queue is None:
            queue = self.default_queue()

        with tracer.start_as_current_span(
            f"run_in_worker {job_class_name}",
            kind=SpanKind.PRODUCER,
            attributes={
                MESSAGING_SYSTEM: "plain.jobs",
                MESSAGING_OPERATION_TYPE: MessagingOperationTypeValues.SEND.value,
                MESSAGING_OPERATION_NAME: "run_in_worker",
                MESSAGING_DESTINATION_NAME: queue,
            },
        ) as span:
            try:
                # Try to automatically annotate the source of the job
                caller = inspect.stack()[1]
                source = f"{caller.filename}:{caller.lineno}"
                span.set_attributes(
                    {
                        CODE_FILEPATH: caller.filename,
                        CODE_LINENO: caller.lineno,
                    }
                )
            except (IndexError, AttributeError):
                source = ""

            parameters = JobParameters.to_json(self._init_args, self._init_kwargs)

            if priority is None:
                priority = self.default_priority()

            if retries is None:
                retries = self.default_retries()

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

            if concurrency_key is None:
                concurrency_key = self.default_concurrency_key()

            # Capture current trace context
            current_span = trace.get_current_span()
            span_context = current_span.get_span_context()

            # Only include trace context if the span is being recorded (sampled)
            # This ensures jobs are only linked to traces that are actually being collected
            if current_span.is_recording() and span_context.is_valid:
                trace_id = f"0x{format_trace_id(span_context.trace_id)}"
                span_id = f"0x{format_span_id(span_context.span_id)}"
            else:
                trace_id = None
                span_id = None

            # Use transaction with optional locking for race-free enqueue
            with transaction.atomic():
                # Acquire lock via context manager (or nullcontext if None)
                with self.get_enqueue_lock(concurrency_key) or nullcontext():
                    # Check with lock held (if using locks)
                    if not self.should_enqueue(concurrency_key):
                        span.set_attribute(ERROR_TYPE, "ShouldNotEnqueue")
                        return None

                    # Create job with lock held
                    job_request = JobRequest(
                        job_class=job_class_name,
                        parameters=parameters,
                        start_at=start_at,
                        source=source,
                        queue=queue,
                        priority=priority,
                        retries=retries,
                        retry_attempt=retry_attempt,
                        concurrency_key=concurrency_key,
                        trace_id=trace_id,
                        span_id=span_id,
                    )
                    job_request.save()

                    span.set_attribute(
                        MESSAGING_MESSAGE_ID,
                        str(job_request.uuid),
                    )

                    # Add job UUID to current span for bidirectional linking
                    span.set_attribute("job.uuid", str(job_request.uuid))
                    span.set_status(trace.StatusCode.OK)

                    return job_request

    def get_requested_jobs(
        self, *, concurrency_key: str | None = None, include_retries: bool = False
    ) -> models.QuerySet:
        """
        Get pending jobs (JobRequest) for this job class.

        Args:
            concurrency_key: Optional concurrency_key to filter by. If None, uses self.job_process.concurrency_key (if available) or self.default_concurrency_key()
            include_retries: If False (default), exclude retry attempts from results
        """
        from .models import JobRequest

        job_class_name = jobs_registry.get_job_class_name(self.__class__)

        if concurrency_key is None:
            if self.job_process:
                concurrency_key = self.job_process.concurrency_key
            else:
                concurrency_key = self.default_concurrency_key()

        filters = {"job_class": job_class_name}
        if concurrency_key:
            filters["concurrency_key"] = concurrency_key

        qs = JobRequest.query.filter(**filters)

        if not include_retries:
            qs = qs.filter(retry_attempt=0)

        return qs

    def get_processing_jobs(
        self,
        *,
        concurrency_key: str | None = None,
        include_retries: bool = False,
        include_self: bool = False,
    ) -> models.QuerySet:
        """
        Get currently processing jobs (JobProcess) for this job class.

        Args:
            concurrency_key: Optional concurrency_key to filter by. If None, uses self.job_process.concurrency_key (if available) or self.default_concurrency_key()
            include_retries: If False (default), exclude retry attempts from results
        """
        from .models import JobProcess

        job_class_name = jobs_registry.get_job_class_name(self.__class__)

        if concurrency_key is None:
            if self.job_process:
                concurrency_key = self.job_process.concurrency_key
            else:
                concurrency_key = self.default_concurrency_key()

        filters = {"job_class": job_class_name}
        if concurrency_key:
            filters["concurrency_key"] = concurrency_key

        qs = JobProcess.query.filter(**filters)

        if not include_retries:
            qs = qs.filter(retry_attempt=0)

        if not include_self and self.job_process:
            qs = qs.exclude(id=self.job_process.id)

        return qs

    def should_enqueue(self, concurrency_key: str) -> bool:
        """
        Called before enqueueing job. Return False to skip.

        Args:
            concurrency_key: The resolved concurrency_key (from default_concurrency_key() or override)

        Default behavior:
        - If concurrency_key is empty: no restrictions (always enqueue)
        - If concurrency_key is set: enforce uniqueness (only one job with this key can be pending or processing)

        Override to implement custom concurrency control:
        - Concurrency limits
        - Rate limits
        - Custom business logic

        Example:
            def should_enqueue(self, concurrency_key):
                # Max 3 processing, 1 pending per concurrency_key
                processing = self.get_processing_jobs(concurrency_key).count()
                pending = self.get_requested_jobs(concurrency_key).count()
                return processing < 3 and pending < 1
        """
        if not concurrency_key:
            # No key = no uniqueness check
            return True

        # Key set = enforce uniqueness (include retries for strong guarantee)
        return (
            self.get_processing_jobs(
                concurrency_key=concurrency_key, include_retries=True
            ).count()
            == 0
            and self.get_requested_jobs(
                concurrency_key=concurrency_key, include_retries=True
            ).count()
            == 0
        )

    def default_concurrency_key(self) -> str:
        """
        Default identifier for this job.

        Use for:
        - Deduplication
        - Grouping related jobs
        - Concurrency control

        Return empty string (default) for no grouping.
        Can be overridden per-call via concurrency_key parameter in run_in_worker().
        """
        return ""

    def default_queue(self) -> str:
        """Default queue for this job. Can be overridden in run_in_worker()."""
        return "default"

    def default_priority(self) -> int:
        """
        Default priority for this job. Can be overridden in run_in_worker().

        Higher numbers run first: 10 > 5 > 0 > -5 > -10
        - Use positive numbers for high priority jobs
        - Use negative numbers for low priority jobs
        - Default is 0
        """
        return 0

    def default_retries(self) -> int:
        """Default number of retry attempts. Can be overridden in run_in_worker()."""
        return 0

    def calculate_retry_delay(self, attempt: int) -> int:
        """
        Calculate a delay in seconds before the next retry attempt.

        On the first retry, attempt will be 1.
        """
        return 0

    def get_enqueue_lock(
        self, concurrency_key: str
    ) -> AbstractContextManager[None] | None:
        """
        Return a context manager for the enqueue lock, or None for no locking.

        Default: PostgreSQL advisory lock (None on SQLite/MySQL or empty concurrency_key).
        Override to provide custom locking (Redis, etcd, etc.).

        The returned context manager is used to wrap the should_enqueue() check
        and job creation, ensuring atomicity.

        Example with Redis:
            def get_enqueue_lock(self, concurrency_key):
                import redis
                return redis_client.lock(f"job:{concurrency_key}", timeout=5)

        Example with custom implementation:
            from contextlib import contextmanager

            @contextmanager
            def get_enqueue_lock(self, concurrency_key):
                my_lock.acquire(concurrency_key)
                try:
                    yield
                finally:
                    my_lock.release(concurrency_key)

        To disable locking:
            def get_enqueue_lock(self, concurrency_key):
                return None
        """
        # No locking if no concurrency_key
        if not concurrency_key:
            return None

        # PostgreSQL: use advisory locks
        if db_connection.vendor == "postgresql":
            return postgres_advisory_lock(self, concurrency_key)

        # Other databases: no locking
        return None
