import datetime
import inspect
import logging

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

from plain.models import IntegrityError
from plain.utils import timezone

from .registry import JobParameters, jobs_registry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("plain.worker")


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

        job_class_name = jobs_registry.get_job_class_name(self.__class__)

        if queue is None:
            queue = self.get_queue()

        with tracer.start_as_current_span(
            f"run_in_worker {job_class_name}",
            kind=SpanKind.PRODUCER,
            attributes={
                MESSAGING_SYSTEM: "plain.worker",
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
                    span.set_attribute(ERROR_TYPE, "DuplicateJob")
                    return running

            # Is recording is not enough here... because we also record for summaries!

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

            try:
                job_request = JobRequest(
                    job_class=job_class_name,
                    parameters=parameters,
                    start_at=start_at,
                    source=source,
                    queue=queue,
                    priority=priority,
                    retries=retries,
                    retry_attempt=retry_attempt,
                    unique_key=unique_key,
                    trace_id=trace_id,
                    span_id=span_id,
                )
                job_request.save(
                    clean_and_validate=False
                )  # So IntegrityError is raised on unique instead of potentially confusing ValidationError...

                span.set_attribute(
                    MESSAGING_MESSAGE_ID,
                    str(job_request.uuid),
                )

                # Add job UUID to current span for bidirectional linking
                span.set_attribute("job.uuid", str(job_request.uuid))
                span.set_status(trace.StatusCode.OK)

                return job_request
            except IntegrityError as e:
                span.set_attribute(ERROR_TYPE, "IntegrityError")
                span.set_status(trace.Status(trace.StatusCode.ERROR, "Duplicate job"))
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
        Calculate a delay in seconds before the next retry attempt.

        On the first retry, attempt will be 1.
        """
        return 0
