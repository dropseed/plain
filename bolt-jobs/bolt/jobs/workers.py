import logging
import multiprocessing
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor

from bolt.db import transaction
from bolt.logs import app_logger
from bolt.signals import request_finished, request_started

from .models import Job, JobRequest, JobResult, JobResultStatuses

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

        self.uuid = uuid.uuid4()

    def run(self):
        logger.info(
            "Starting job worker with %s max processes",
            self.max_processes,
        )

        while True:
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

                job = job_request.convert_to_job(worker_uuid=self.uuid)

            job_uuid = str(job.uuid)  # Make a str copy

            # Release these now
            del job_request
            del job

            self.executor.submit(process_job, job_uuid)

    def shutdown(self):
        # Prevent duplicate keyboard and sigterm calls
        # (the way this works also only lets us shutdown once per instance)
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True

        logger.info("Job worker shutdown started")

        # Make an attept to immediatelly move any unstarted jobs from this worker
        # to the JobResults as cancelled. If they have a retry, they'll be picked
        # up by the next worker process.
        for job in Job.objects.filter(worker_uuid=self.uuid, started_at__isnull=True):
            job.convert_to_result(status=JobResultStatuses.CANCELLED)

        # Now shutdown the process pool.
        # There's still some chance of a race condition here where we
        # just deleted a Job and it was still picked up, but we'll log
        # missing jobs as warnings instead of exceptions.
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
        num_proccesses = len(self.executor._processes)
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


def process_job(job_uuid):
    try:
        worker_pid = os.getpid()

        request_started.send(sender=None)

        try:
            job = Job.objects.get(uuid=job_uuid)
        except Job.DoesNotExist:
            logger.warning(
                "Job not found worker_pid=%s job_uuid=%s",
                worker_pid,
                job_uuid,
            )
            return

        logger.info(
            'Executing job worker_pid=%s job_class=%s job_request_uuid=%s job_priority=%s job_source="%s"',
            worker_pid,
            job.job_class,
            job.job_request_uuid,
            job.priority,
            job.source,
        )

        app_logger.kv.context["job_request_uuid"] = str(job.job_request_uuid)
        app_logger.kv.context["job_uuid"] = str(job.uuid)

        job_result = job.run()

        # Release it now
        del job

        app_logger.kv.context.pop("job_request_uuid", None)
        app_logger.kv.context.pop("job_uuid", None)

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
    except Exception as e:
        # Raising exceptions inside the worker process doesn't
        # seem to be caught/shown anywhere as configured.
        # So we at least log it out here.
        # (A job should catch it's own user-code errors, so this is for library errors)
        logger.exception(e)
    finally:
        request_finished.send(sender=None)