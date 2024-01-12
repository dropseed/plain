import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor

from bolt.db import transaction
from bolt.logs import app_logger
from bolt.signals import request_finished, request_started

from .models import JobRequest, JobResult

logger = logging.getLogger("bolt.jobs")


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

    def run(self):
        logger.info(
            "Starting job worker with %s max processes",
            self.max_processes,
        )

        try:
            while True:
                self.maybe_log_stats()
                self.maybe_check_job_results()

                with transaction.atomic():
                    next_job = JobRequest.objects.next_up()
                    if not next_job:
                        # Potentially no jobs to process (who knows for how long)
                        # but sleep for a second to give the CPU and DB a break
                        time.sleep(1)
                        continue

                    logger.info(
                        'Preparing to execute job job_class=%s job_request_uuid=%s job_priority=%s job_source="%s"',
                        next_job.job_class,
                        next_job.uuid,
                        next_job.priority,
                        next_job.source,
                    )

                    job_result = next_job.convert_to_result()

                job_result_uuid = str(job_result.uuid)  # Make a str copy

                # Release these now
                del next_job
                del job_result

                self.executor.submit(process_job_result, job_result_uuid)

        except (KeyboardInterrupt, SystemExit):
            self.executor.shutdown(wait=True, cancel_futures=True)

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
        num_proccesses = len(self.executor._processes)
        num_backlog_jobs = JobRequest.objects.count()
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
        JobResult.objects.mark_lost_jobs()
        JobResult.objects.retry_failed_jobs()


def process_job_result(job_result_uuid):
    worker_pid = os.getpid()

    request_started.send(sender=None)
    job_result = JobResult.objects.get(uuid=job_result_uuid)

    logger.info(
        'Executing job worker_pid=%s job_class=%s job_request_uuid=%s job_priority=%s job_source="%s"',
        worker_pid,
        job_result.job_class,
        job_result.job_request_uuid,
        job_result.priority,
        job_result.source,
    )

    app_logger.kv.context["job_request_uuid"] = str(job_result.job_request_uuid)
    app_logger.kv.context["job_result_uuid"] = str(job_result.uuid)

    job_result.process_job()

    app_logger.kv.context.pop("job_request_uuid", None)
    app_logger.kv.context.pop("job_result_uuid", None)

    duration = job_result.ended_at - job_result.started_at
    duration = duration.total_seconds()

    logger.info(
        'Completed job worker_pid=%s job_class=%s job_request_uuid=%s job_result_uuid=%s job_priority=%s job_source="%s" job_duration=%s',
        worker_pid,
        job_result.job_class,
        job_result.job_request_uuid,
        job_result.uuid,
        job_result.priority,
        job_result.source,
        duration,
    )

    request_finished.send(sender=None)
