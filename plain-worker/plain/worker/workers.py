import gc
import logging
import multiprocessing
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from functools import partial

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_FUNCTION_NAME,
    CODE_NAMESPACE,
)
from opentelemetry.semconv._incubating.attributes.messaging_attributes import (
    MESSAGING_BATCH_MESSAGE_COUNT,
    MESSAGING_CONSUMER_GROUP_NAME,
    MESSAGING_DESTINATION_NAME,
    MESSAGING_MESSAGE_BODY_SIZE,
    MESSAGING_MESSAGE_CONVERSATION_ID,
    MESSAGING_MESSAGE_ID,
    MESSAGING_OPERATION_NAME,
    MESSAGING_OPERATION_TYPE,
    MESSAGING_SYSTEM,
    MessagingOperationTypeValues,
)
from opentelemetry.semconv._incubating.attributes.process_attributes import (
    PROCESS_PID,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.trace import SpanKind

from plain import models
from plain.models import transaction
from plain.runtime import settings
from plain.signals import request_finished, request_started
from plain.utils import timezone
from plain.utils.module_loading import import_string

from .models import Job, JobRequest, JobResult, JobResultStatuses
from .registry import jobs_registry

logger = logging.getLogger("plain.worker")
tracer = trace.get_tracer("plain.worker")


class Worker:
    def __init__(
        self,
        queues,
        jobs_schedule=None,
        max_processes=None,
        max_jobs_per_process=None,
        max_pending_per_process=10,
        stats_every=None,
    ):
        if jobs_schedule is None:
            jobs_schedule = []

        self.executor = ProcessPoolExecutor(
            max_workers=max_processes,
            max_tasks_per_child=max_jobs_per_process,
            mp_context=multiprocessing.get_context("spawn"),
        )

        self.queues = queues

        # Filter the jobs schedule to those that are in the same queue as this worker
        self.jobs_schedule = [x for x in jobs_schedule if x[0].get_queue() in queues]

        # How often to log the stats (in seconds)
        self.stats_every = stats_every

        self.max_processes = self.executor._max_workers
        self.max_jobs_per_process = max_jobs_per_process
        self.max_pending_per_process = max_pending_per_process

        self._is_shutting_down = False

    def run(self):
        logger.info(
            "⬣ Starting Plain worker\n    Registered jobs: %s\n    Queues: %s\n    Jobs schedule: %s\n    Stats every: %s seconds\n    Max processes: %s\n    Max jobs per process: %s\n    Max pending per process: %s\n    PID: %s",
            "\n                     ".join(
                f"{name}: {cls}" for name, cls in jobs_registry.jobs.items()
            ),
            ", ".join(self.queues),
            "\n                   ".join(str(x) for x in self.jobs_schedule),
            self.stats_every,
            self.max_processes,
            self.max_jobs_per_process,
            self.max_pending_per_process,
            os.getpid(),
        )

        while not self._is_shutting_down:
            try:
                self.maybe_log_stats()
                self.maybe_check_job_results()
                self.maybe_schedule_jobs()
            except Exception as e:
                # Log the issue, but don't stop the worker
                # (these tasks are kind of ancilarry to the main job processing)
                logger.exception(e)

            if len(self.executor._pending_work_items) >= (
                self.max_processes * self.max_pending_per_process
            ):
                # We don't want to convert too many JobRequests to Jobs,
                # because anything not started yet will be cancelled on deploy etc.
                # It's easier to leave them in the JobRequest db queue as long as possible.
                time.sleep(0.1)
                continue

            with tracer.start_as_current_span(
                "receive job_queue",
                kind=SpanKind.CLIENT,
                attributes={
                    MESSAGING_SYSTEM: "plain.worker",
                    MESSAGING_OPERATION_TYPE: MessagingOperationTypeValues.RECEIVE.value,
                    MESSAGING_OPERATION_NAME: "receive",
                },
            ) as span:
                with transaction.atomic():
                    job_request = (
                        JobRequest.objects.select_for_update(skip_locked=True)
                        .filter(
                            queue__in=self.queues,
                        )
                        .filter(
                            models.Q(start_at__isnull=True)
                            | models.Q(start_at__lte=timezone.now())
                        )
                        .order_by("priority", "-start_at", "-created_at")
                        .first()
                    )
                    if not job_request:
                        # Potentially no jobs to process (who knows for how long)
                        # but sleep for a second to give the CPU and DB a break
                        time.sleep(1)
                        continue

                    span.set_attributes(
                        {
                            MESSAGING_DESTINATION_NAME: job_request.queue,
                            MESSAGING_MESSAGE_ID: str(job_request.uuid),
                            MESSAGING_MESSAGE_BODY_SIZE: len(job_request.parameters)
                            if job_request.parameters
                            else 0,
                        }
                    )

                    logger.info(
                        'Preparing to execute job job_class=%s job_request_uuid=%s job_priority=%s job_source="%s" job_queues="%s"',
                        job_request.job_class,
                        job_request.uuid,
                        job_request.priority,
                        job_request.source,
                        job_request.queue,
                    )

                    job = job_request.convert_to_job()

            job_uuid = str(job.uuid)  # Make a str copy

            # Release these now
            del job_request
            del job

            future = self.executor.submit(process_job, job_uuid)
            future.add_done_callback(partial(future_finished_callback, job_uuid))

            # Do a quick sleep regardless to see if it
            # gives processes a chance to start up
            time.sleep(0.1)

    def shutdown(self):
        if self._is_shutting_down:
            # Already shutting down somewhere else
            return

        logger.info("Job worker shutdown started")
        self._is_shutting_down = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        logger.info("Job worker shutdown complete")

    def maybe_log_stats(self):
        if not self.stats_every:
            return

        now = time.time()

        if not hasattr(self, "_stats_logged_at"):
            self._stats_logged_at = now

        if now - self._stats_logged_at > self.stats_every:
            self._stats_logged_at = now
            self.log_stats()

    def maybe_check_job_results(self):
        now = time.time()

        if not hasattr(self, "_job_results_checked_at"):
            self._job_results_checked_at = now

        check_every = 60  # Only need to check once a minute

        if now - self._job_results_checked_at > check_every:
            self._job_results_checked_at = now
            self.rescue_job_results()

    def maybe_schedule_jobs(self):
        if not self.jobs_schedule:
            return

        now = time.time()

        if not hasattr(self, "_jobs_schedule_checked_at"):
            self._jobs_schedule_checked_at = now

        check_every = 60  # Only need to check once every 60 seconds

        if now - self._jobs_schedule_checked_at > check_every:
            with tracer.start_as_current_span("worker.schedule_jobs") as span:
                span.set_attribute(
                    MESSAGING_BATCH_MESSAGE_COUNT, len(self.jobs_schedule)
                )

                for job, schedule in self.jobs_schedule:
                    next_start_at = schedule.next()

                    # Leverage the unique_key to prevent duplicate scheduled
                    # jobs with the same start time (also works if unique_key == "")
                    schedule_unique_key = f"{job.get_unique_key()}:scheduled:{int(next_start_at.timestamp())}"

                    # Drawback here is if scheduled job is running, and detected by unique_key
                    # so it doesn't schedule the next one? Maybe an ok downside... prevents
                    # overlapping executions...?
                    result = job.run_in_worker(
                        delay=next_start_at,
                        unique_key=schedule_unique_key,
                    )
                    # Results are a list if it found scheduled/running jobs...
                    if not isinstance(result, list):
                        logger.info(
                            'Scheduling job job_class=%s job_queue="%s" job_start_at="%s" job_schedule="%s" job_unique_key="%s"',
                            result.job_class,
                            result.queue,
                            result.start_at,
                            schedule,
                            result.unique_key,
                        )

                self._jobs_schedule_checked_at = now

    def log_stats(self):
        try:
            num_proccesses = len(self.executor._processes)
        except (AttributeError, TypeError):
            # Depending on shutdown timing and internal behavior, this might not work
            num_proccesses = 0

        jobs_requested = JobRequest.objects.filter(queue__in=self.queues).count()
        jobs_processing = Job.objects.filter(queue__in=self.queues).count()

        logger.info(
            'Job worker stats worker_processes=%s worker_queues="%s" jobs_requested=%s jobs_processing=%s worker_max_processes=%s worker_max_jobs_per_process=%s',
            num_proccesses,
            ",".join(self.queues),
            jobs_requested,
            jobs_processing,
            self.max_processes,
            self.max_jobs_per_process,
        )

    def rescue_job_results(self):
        """Find any lost or failed jobs on this worker's queues and handle them."""
        with tracer.start_as_current_span("worker.rescue_jobs"):
            # Queue information is already in the messaging destination attributes
            # TODO return results and log them if there are any?
            Job.objects.filter(queue__in=self.queues).mark_lost_jobs()
            JobResult.objects.filter(queue__in=self.queues).retry_failed_jobs()


def future_finished_callback(job_uuid: str, future: Future):
    if future.cancelled():
        logger.warning("Job cancelled job_uuid=%s", job_uuid)
        job = Job.objects.get(uuid=job_uuid)
        job.convert_to_result(status=JobResultStatuses.CANCELLED)
    else:
        logger.debug("Job finished job_uuid=%s", job_uuid)


def process_job(job_uuid):
    with tracer.start_as_current_span("process job", kind=SpanKind.CONSUMER) as span:
        try:
            worker_pid = os.getpid()
            span.set_attributes(
                {
                    MESSAGING_SYSTEM: "plain.worker",
                    MESSAGING_OPERATION_TYPE: MessagingOperationTypeValues.PROCESS.value,
                    MESSAGING_OPERATION_NAME: "process",
                    MESSAGING_MESSAGE_ID: job_uuid,
                    PROCESS_PID: worker_pid,
                }
            )

            request_started.send(sender=None)

            job = Job.objects.get(uuid=job_uuid)

            span.set_attributes(
                {
                    MESSAGING_DESTINATION_NAME: job.queue,
                    MESSAGING_CONSUMER_GROUP_NAME: job.queue,  # Workers consume from specific queues
                    CODE_NAMESPACE: job.job_class,
                }
            )

            logger.info(
                'Executing job worker_pid=%s job_class=%s job_request_uuid=%s job_priority=%s job_source="%s" job_queue="%s"',
                worker_pid,
                job.job_class,
                job.job_request_uuid,
                job.priority,
                job.source,
                job.queue,
            )

            def middleware_chain(job):
                with tracer.start_as_current_span(
                    f"job.run.{job.job_class}"
                ) as job_span:
                    job_span.set_attributes(
                        {
                            CODE_FUNCTION_NAME: "run",
                            CODE_NAMESPACE: job.job_class,
                        }
                    )
                    return job.run()

            for middleware_path in reversed(settings.WORKER_MIDDLEWARE):
                middleware_class = import_string(middleware_path)
                middleware_instance = middleware_class(middleware_chain)
                middleware_chain = middleware_instance

            job_result = middleware_chain(job)

            # Release it now
            del job

            duration = job_result.ended_at - job_result.started_at
            duration = duration.total_seconds()

            span.set_attributes(
                {
                    MESSAGING_MESSAGE_CONVERSATION_ID: str(
                        job_result.job_request_uuid
                    ),  # Links back to original request
                }
            )

            logger.info(
                'Completed job worker_pid=%s job_class=%s job_uuid=%s job_request_uuid=%s job_result_uuid=%s job_priority=%s job_source="%s" job_queue="%s" job_duration=%s',
                worker_pid,
                job_result.job_class,
                job_result.job_uuid,
                job_result.job_request_uuid,
                job_result.uuid,
                job_result.priority,
                job_result.source,
                job_result.queue,
                duration,
            )

            del job_result
        except Exception as e:
            # Raising exceptions inside the worker process doesn't
            # seem to be caught/shown anywhere as configured.
            # So we at least log it out here.
            # (A job should catch it's own user-code errors, so this is for library errors)
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            span.set_attribute(ERROR_TYPE, type(e).__name__)
            logger.exception(e)
        finally:
            request_finished.send(sender=None)
            gc.collect()
