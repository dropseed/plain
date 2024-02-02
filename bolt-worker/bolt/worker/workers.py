import gc
import logging
import multiprocessing
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from functools import partial

from bolt.db import transaction
from bolt.runtime import settings
from bolt.signals import request_finished, request_started
from bolt.utils.module_loading import import_string

from .models import Job, JobRequest, JobResult, JobResultStatuses

logger = logging.getLogger("bolt.worker")


class Worker:
    def __init__(self, max_processes=None, max_jobs_per_process=None, stats_every=None):
        self.executor = ProcessPoolExecutor(
            max_workers=max_processes,
            max_tasks_per_child=max_jobs_per_process,
            mp_context=multiprocessing.get_context("spawn"),
        )

        # How often to log the stats (in seconds)
        self.stats_every = stats_every

        self.max_processes = self.executor._max_workers
        self.max_jobs_per_process = max_jobs_per_process

        self._is_shutting_down = False

    def run(self):
        logger.info(
            "Starting job worker with %s max processes",
            self.max_processes,
        )

        while not self._is_shutting_down:
            try:
                self.maybe_log_stats()
                self.maybe_check_job_results()
            except Exception as e:
                # Log the issue, but don't stop the worker
                # (these tasks are kind of ancilarry to the main job processing)
                logger.exception(e)

            with transaction.atomic():
                job_request = JobRequest.objects.next_up()
                if not job_request:
                    # Potentially no jobs to process (who knows for how long)
                    # but sleep for a second to give the CPU and DB a break
                    time.sleep(1)
                    continue

                logger.info(
                    'Preparing to execute job job_class=%s job_request_uuid=%s job_priority=%s job_source="%s"',
                    job_request.job_class,
                    job_request.uuid,
                    job_request.priority,
                    job_request.source,
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
            self.check_job_results()

    def log_stats(self):
        try:
            num_proccesses = len(self.executor._processes)
        except (AttributeError, TypeError):
            # Depending on shutdown timing and internal behavior, this might not work
            num_proccesses = 0

        num_backlog_jobs = (
            JobRequest.objects.count()
            + Job.objects.filter(started_at__isnull=True).count()
        )
        if num_backlog_jobs > 0:
            # Basically show how many jobs aren't about to be picked
            # up in this same tick (so if there's 1, we don't really need to log that as a backlog)
            num_backlog_jobs = num_backlog_jobs - 1
        logger.info(
            "Job worker stats worker_processes=%s jobs_backlog=%s worker_max_processes=%s worker_max_jobs_per_process=%s",
            num_proccesses,
            num_backlog_jobs,
            self.max_processes,
            self.max_jobs_per_process,
        )

    def check_job_results(self):
        Job.objects.mark_lost_jobs()
        JobResult.objects.retry_failed_jobs()


def future_finished_callback(job_uuid: str, future: Future):
    if future.cancelled():
        logger.warning("Job cancelled job_uuid=%s", job_uuid)
        job = Job.objects.get(uuid=job_uuid)
        job.convert_to_result(status=JobResultStatuses.CANCELLED)
    else:
        logger.debug("Job finished job_uuid=%s", job_uuid)


def process_job(job_uuid):
    try:
        worker_pid = os.getpid()

        request_started.send(sender=None)

        job = Job.objects.get(uuid=job_uuid)

        logger.info(
            'Executing job worker_pid=%s job_class=%s job_request_uuid=%s job_priority=%s job_source="%s"',
            worker_pid,
            job.job_class,
            job.job_request_uuid,
            job.priority,
            job.source,
        )

        middleware_chain = lambda job: job.run()

        for middleware_path in reversed(settings.WORKER_MIDDLEWARE):
            middleware_class = import_string(middleware_path)
            middleware_instance = middleware_class(middleware_chain)
            middleware_chain = middleware_instance

        job_result = middleware_chain(job)

        # Release it now
        del job

        duration = job_result.ended_at - job_result.started_at
        duration = duration.total_seconds()

        logger.info(
            'Completed job worker_pid=%s job_class=%s job_uuid=%s job_request_uuid=%s job_result_uuid=%s job_priority=%s job_source="%s" job_duration=%s',
            worker_pid,
            job_result.job_class,
            job_result.job_uuid,
            job_result.job_request_uuid,
            job_result.uuid,
            job_result.priority,
            job_result.source,
            duration,
        )

        del job_result
    except Exception as e:
        # Raising exceptions inside the worker process doesn't
        # seem to be caught/shown anywhere as configured.
        # So we at least log it out here.
        # (A job should catch it's own user-code errors, so this is for library errors)
        logger.exception(e)
    finally:
        request_finished.send(sender=None)
        gc.collect()
