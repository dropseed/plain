from __future__ import annotations

import gc
import logging
import multiprocessing
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any

from plain import models
from plain.models import transaction
from plain.runtime import settings
from plain.signals import request_finished, request_started
from plain.utils import timezone
from plain.utils.module_loading import import_string

from .registry import jobs_registry

if TYPE_CHECKING:
    from .models import JobResult

# Models are NOT imported at the top of this file!
# See comment on _worker_process_initializer() for explanation.

logger = logging.getLogger("plain.jobs")


def _worker_process_initializer() -> None:
    """Initialize Plain framework in worker process before processing jobs.

    Why this is needed:
    - We use multiprocessing with 'spawn' context (not 'fork')
    - Spawn creates fresh Python processes, not forked copies
    - When a spawned process starts, it re-imports this module BEFORE the initializer runs
    - If we imported models at the top of this file, model registration would
      happen before plain.runtime.setup(), causing PackageRegistryNotReady errors

    Solution:
    - This initializer runs plain.runtime.setup() FIRST in each worker process
    - All model imports happen lazily inside functions (after setup completes)
    - This ensures packages registry is ready before any models are accessed

    Execution order in spawned worker:
    1. Re-import workers.py (but models NOT imported yet - lazy!)
    2. Run this initializer → plain.runtime.setup()
    3. Execute process_job() → NOW it's safe to import models
    """
    from plain.runtime import setup

    # Each spawned worker process needs to set up Plain
    # (spawn context creates fresh processes, not forks)
    setup()


class Worker:
    def __init__(
        self,
        queues: list[str],
        jobs_schedule: list[Any] | None = None,
        max_processes: int | None = None,
        max_jobs_per_process: int | None = None,
        max_pending_per_process: int = 10,
        stats_every: int | None = None,
    ) -> None:
        if jobs_schedule is None:
            jobs_schedule = []

        self.executor = ProcessPoolExecutor(
            max_workers=max_processes,
            max_tasks_per_child=max_jobs_per_process,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_worker_process_initializer,
        )

        self.queues = queues

        # Filter the jobs schedule to those that are in the same queue as this worker
        self.jobs_schedule = [
            x for x in jobs_schedule if x[0].default_queue() in queues
        ]

        # How often to log the stats (in seconds)
        self.stats_every = stats_every

        self.max_processes = self.executor._max_workers
        self.max_jobs_per_process = max_jobs_per_process
        self.max_pending_per_process = max_pending_per_process

        self._is_shutting_down = False

    def run(self) -> None:
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import JobRequest

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
                time.sleep(0.5)
                continue

            with transaction.atomic():
                job_request = (
                    JobRequest.query.select_for_update(skip_locked=True)
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

                logger.debug(
                    'Preparing to execute job job_class=%s job_request_uuid=%s job_priority=%s job_source="%s" job_queues="%s"',
                    job_request.job_class,
                    job_request.uuid,
                    job_request.priority,
                    job_request.source,
                    job_request.queue,
                )

                job = job_request.convert_to_job_process()

            job_process_uuid = str(job.uuid)  # Make a str copy

            future = self.executor.submit(process_job, job_process_uuid)
            future.add_done_callback(
                partial(future_finished_callback, job_process_uuid)
            )

    def shutdown(self) -> None:
        if self._is_shutting_down:
            # Already shutting down somewhere else
            return

        logger.info("Job worker shutdown started")
        self._is_shutting_down = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        logger.info("Job worker shutdown complete")

    def maybe_log_stats(self) -> None:
        if not self.stats_every:
            return

        now = time.time()

        if not hasattr(self, "_stats_logged_at"):
            self._stats_logged_at = now

        if now - self._stats_logged_at > self.stats_every:
            self._stats_logged_at = now
            self.log_stats()

    def maybe_check_job_results(self) -> None:
        now = time.time()

        if not hasattr(self, "_job_results_checked_at"):
            self._job_results_checked_at = now

        check_every = 60  # Only need to check once a minute

        if now - self._job_results_checked_at > check_every:
            self._job_results_checked_at = now
            self.rescue_job_results()

    def maybe_schedule_jobs(self) -> None:
        if not self.jobs_schedule:
            return

        now = time.time()

        if not hasattr(self, "_jobs_schedule_checked_at"):
            self._jobs_schedule_checked_at = now

        check_every = 60  # Only need to check once every 60 seconds

        if now - self._jobs_schedule_checked_at > check_every:
            for job, schedule in self.jobs_schedule:
                next_start_at = schedule.next()

                # Leverage the concurrency_key to group scheduled jobs
                # with the same start time
                schedule_concurrency_key = f"{job.default_concurrency_key()}:scheduled:{int(next_start_at.timestamp())}"

                # Job's should_enqueue hook can control scheduling behavior
                result = job.run_in_worker(
                    delay=next_start_at,
                    concurrency_key=schedule_concurrency_key,
                )
                # Result is None if should_enqueue returned False
                if result:
                    logger.info(
                        'Scheduling job job_class=%s job_queue="%s" job_start_at="%s" job_schedule="%s" concurrency_key="%s"',
                        result.job_class,
                        result.queue,
                        result.start_at,
                        schedule,
                        result.concurrency_key,
                    )

            self._jobs_schedule_checked_at = now

    def log_stats(self) -> None:
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import JobProcess, JobRequest

        try:
            num_proccesses = len(self.executor._processes)
        except (AttributeError, TypeError):
            # Depending on shutdown timing and internal behavior, this might not work
            num_proccesses = 0

        jobs_requested = JobRequest.query.filter(queue__in=self.queues).count()
        jobs_processing = JobProcess.query.filter(queue__in=self.queues).count()

        logger.info(
            'Job worker stats worker_processes=%s worker_queues="%s" jobs_requested=%s jobs_processing=%s worker_max_processes=%s worker_max_jobs_per_process=%s',
            num_proccesses,
            ",".join(self.queues),
            jobs_requested,
            jobs_processing,
            self.max_processes,
            self.max_jobs_per_process,
        )

    def rescue_job_results(self) -> None:
        """Find any lost or failed jobs on this worker's queues and handle them."""
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import JobProcess, JobResult

        # TODO return results and log them if there are any?
        JobProcess.query.filter(queue__in=self.queues).mark_lost_jobs()
        JobResult.query.filter(queue__in=self.queues).retry_failed_jobs()


def future_finished_callback(job_process_uuid: str, future: Future) -> None:
    # Lazy import - see _worker_process_initializer() comment for why
    from .models import JobProcess, JobResultStatuses

    if future.cancelled():
        logger.warning("Job cancelled job_process_uuid=%s", job_process_uuid)
        try:
            job = JobProcess.query.get(uuid=job_process_uuid)
            job.convert_to_result(status=JobResultStatuses.CANCELLED)
        except JobProcess.DoesNotExist:
            # Job may have already been cleaned up
            pass
    elif exception := future.exception():
        # Process pool may have been killed...
        logger.warning(
            "Job failed job_process_uuid=%s",
            job_process_uuid,
            exc_info=exception,
        )
        try:
            job = JobProcess.query.get(uuid=job_process_uuid)
            job.convert_to_result(status=JobResultStatuses.CANCELLED)
        except JobProcess.DoesNotExist:
            # Job may have already been cleaned up
            pass
    else:
        logger.debug("Job finished job_process_uuid=%s", job_process_uuid)


def process_job(job_process_uuid: str) -> None:
    # Lazy import - see _worker_process_initializer() comment for why
    from .models import JobProcess

    try:
        worker_pid = os.getpid()

        request_started.send(sender=None)

        job_process = JobProcess.query.get(uuid=job_process_uuid)

        logger.info(
            'Executing job worker_pid=%s job_class=%s job_request_uuid=%s job_priority=%s job_source="%s" job_queue="%s"',
            worker_pid,
            job_process.job_class,
            job_process.job_request_uuid,
            job_process.priority,
            job_process.source,
            job_process.queue,
        )

        def middleware_chain(job: JobProcess) -> JobResult:
            return job.run()

        for middleware_path in reversed(settings.JOBS_MIDDLEWARE):
            middleware_class = import_string(middleware_path)
            middleware_instance = middleware_class(middleware_chain)
            middleware_chain = middleware_instance.process_job

        job_result = middleware_chain(job_process)

        duration = job_result.ended_at - job_result.started_at  # type: ignore[unsupported-operator]
        duration = duration.total_seconds()

        logger.info(
            'Completed job worker_pid=%s job_class=%s job_process_uuid=%s job_request_uuid=%s job_result_uuid=%s job_priority=%s job_source="%s" job_queue="%s" job_duration=%s',
            worker_pid,
            job_result.job_class,
            job_result.job_process_uuid,
            job_result.job_request_uuid,
            job_result.uuid,
            job_result.priority,
            job_result.source,
            job_result.queue,
            duration,
        )
    except Exception as e:
        # Raising exceptions inside the worker process doesn't
        # seem to be caught/shown anywhere as configured.
        # So we at least log it out here.
        # (A job should catch it's own user-code errors, so this is for library errors)
        logger.exception(e)
    finally:
        request_finished.send(sender=None)
        gc.collect()
