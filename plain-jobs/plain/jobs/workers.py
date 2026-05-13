from __future__ import annotations

import datetime
import gc
import multiprocessing
import os
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

from plain.logs import get_framework_logger
from plain.postgres import transaction
from plain.postgres.db import return_database_connection
from plain.runtime import settings
from plain.utils import timezone
from plain.utils.module_loading import import_string
from plain.utils.os import get_cpu_count
from plain.utils.otel import format_exception_type

from .otel import WorkerMetrics, tracer
from .registry import jobs_registry

if TYPE_CHECKING:
    from .models import JobResult

# Models are NOT imported at the top of this file!
# See comment on _worker_process_initializer() for explanation.

logger = get_framework_logger()


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

        if max_processes is None:
            max_processes = get_cpu_count()

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

        self.max_processes = self.executor._max_workers  # ty: ignore[unresolved-attribute]
        self.max_jobs_per_process = max_jobs_per_process
        self.max_pending_per_process = max_pending_per_process

        self._is_shutting_down = False

        self.worker_id = uuid.uuid4()
        self._hostname = socket.gethostname()
        self._pid = os.getpid()
        self._heartbeat_at = 0.0
        # We refuse to claim JobRequests until a WorkerHeartbeat row exists
        # for our worker_id. Otherwise an unregistered worker could stamp
        # JobProcess rows with a worker_id that has no heartbeat row to ever
        # match — rescue would never find them.
        self._heartbeat_registered = False

        # Track our own in-flight futures so the shutdown drain doesn't depend
        # on ProcessPoolExecutor's private _pending_work_items dict (which
        # isn't guaranteed to drain cleanly when cancel_futures=True is used).
        # The mapping (Future → JobProcess.uuid) also lets _rescue_own_orphans
        # reconcile DB rows against currently-tracked futures. Done callbacks
        # fire from the executor's management thread, so all access goes
        # through _inflight_lock to keep iteration safe.
        self._inflight_futures: dict[Future, str] = {}
        self._inflight_lock = threading.Lock()

        self.metrics = WorkerMetrics(self)

    def run(self) -> None:
        logger.info(
            "Starting Plain worker",
            extra={
                "registered_jobs": list(jobs_registry.jobs.keys()),
                "queues": list(self.queues),
                "jobs_schedule": [str(x) for x in self.jobs_schedule],
                "stats_every": self.stats_every,
                "max_processes": self.max_processes,
                "max_jobs_per_process": self.max_jobs_per_process,
                "max_pending_per_process": self.max_pending_per_process,
                "pid": self._pid,
                "worker_id": str(self.worker_id),
            },
        )

        self.register_heartbeat()
        self._run_loop()
        self._drain_with_heartbeat()
        # Only reached on clean exit. On error/interrupt, control unwinds past
        # this and the heartbeat row is left to go stale — rescue then picks
        # up our in-flight jobs as LOST. Deleting the row here on error would
        # lie about being alive and strand any JobProcess rows still stamped
        # with this worker_id.
        self.deregister_heartbeat()

    def _discard_inflight(self, future: Future) -> None:
        with self._inflight_lock:
            self._inflight_futures.pop(future, None)

    def _drain_with_heartbeat(self) -> None:
        """Wait for in-flight jobs to finish while keeping our heartbeat alive.

        Without continuing to heartbeat during drain, a long-running job
        (e.g. multi-minute LLM turns) would let our row go stale and trigger
        false-positive LOST conversions from another worker's rescue tick.

        Drain is unbounded — a stuck job will block here until the platform
        sends SIGKILL (Heroku's grace period, k8s terminationGracePeriod, etc.).
        At that point the heartbeat goes stale and rescue picks up the orphans.
        """
        self.executor.shutdown(wait=False, cancel_futures=True)
        while True:
            # Snapshot under the lock — done callbacks mutate the set from
            # the executor's management thread.
            with self._inflight_lock:
                snapshot = list(self._inflight_futures.keys())
            if not snapshot:
                break
            # Sleep up to 1s, waking early if any future completes.
            wait(snapshot, timeout=1)
            try:
                self.maybe_heartbeat()
            except Exception as e:
                logger.exception(e)
        logger.info("Job worker shutdown complete")

    def _run_loop(self) -> None:
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import JobRequest

        while not self._is_shutting_down:
            with tracer.start_as_current_span(
                "worker loop", kind=trace.SpanKind.CONSUMER
            ) as span:
                try:
                    self.maybe_heartbeat()
                    self.maybe_log_stats()
                    self.maybe_check_job_results()
                    self.maybe_schedule_jobs()
                except Exception as e:
                    # The catch is inside the span, so the SDK's auto-record
                    # on context exit won't fire — stamp the canonical
                    # failure signal explicitly. Log and continue: these
                    # tasks are ancillary to the main job processing.
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR)
                    span.set_attribute(ERROR_TYPE, format_exception_type(e))
                    logger.exception(e)

            # Re-check shutdown after maintenance — a signal may have arrived
            # between the loop condition and now. Don't pick up new work.
            if self._is_shutting_down:
                break

            if not self._heartbeat_registered:
                time.sleep(1)
                continue

            if len(self._inflight_futures) >= (
                self.max_processes * self.max_pending_per_process
            ):
                # We don't want to convert too many JobRequests to Jobs,
                # because anything not started yet will be cancelled on deploy etc.
                # It's easier to leave them in the JobRequest db queue as long as possible.
                time.sleep(0.5)
                continue

            with transaction.atomic():
                job_request = (
                    JobRequest.query.ready_to_run()
                    .filter(queue__in=self.queues)
                    .select_for_update(skip_locked=True)
                    .order_by("-priority", "-start_at", "-created_at")
                    .first()
                )
                if not job_request:
                    # Potentially no jobs to process (who knows for how long)
                    # but sleep for a second to give the CPU and DB a break
                    time.sleep(1)
                    continue

                logger.debug(
                    "Preparing to execute job",
                    extra={
                        "job_class": job_request.job_class,
                        "job_request_uuid": job_request.uuid,
                        "job_priority": job_request.priority,
                        "job_source": job_request.source,
                        "job_queue": job_request.queue,
                    },
                )

                job = job_request.convert_to_job_process(worker_id=self.worker_id)

            # Signal may have fired during the DB queries above. Don't submit
            # new work past shutdown — revert the JobProcess back to a
            # JobRequest so the next worker generation picks it up.
            if self._is_shutting_down:
                job.revert_to_job_request()
                break

            job_process_uuid = str(job.uuid)  # Make a str copy

            try:
                future = self.executor.submit(process_job, job_process_uuid)
                with self._inflight_lock:
                    self._inflight_futures[future] = job_process_uuid
                future.add_done_callback(
                    partial(future_finished_callback, job_process_uuid)
                )
                future.add_done_callback(self._discard_inflight)
            except (BrokenProcessPool, RuntimeError):
                # BrokenProcessPool: child OOM, segfault, or other crash.
                # RuntimeError: executor already shut down (shutdown race).
                # Either way, the job was already converted from JobRequest
                # to JobProcess, so re-enqueue it before exiting.
                logger.warning(
                    "Process pool broken, re-enqueuing job",
                    extra={"job_process_uuid": job_process_uuid},
                )
                job.revert_to_job_request()
                break

    def shutdown(self) -> None:
        if self._is_shutting_down:
            # Already shutting down somewhere else
            return

        logger.info("Job worker shutdown requested")
        # Just flip the flag — drain happens in _drain_with_heartbeat() so
        # heartbeats keep firing during it. Blocking the signal handler with
        # executor.shutdown(wait=True) here would let our row go stale.
        self._is_shutting_down = True

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

    def _create_heartbeat_row(self) -> None:
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import WorkerHeartbeat

        WorkerHeartbeat.query.create(
            worker_id=self.worker_id,
            hostname=self._hostname,
            pid=self._pid,
            queues=list(self.queues),
            last_heartbeat_at=timezone.now(),
        )

    def _refresh_heartbeat(self) -> None:
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import WorkerHeartbeat

        updated = WorkerHeartbeat.query.filter(worker_id=self.worker_id).update(
            last_heartbeat_at=timezone.now()
        )
        if not updated:
            # Row was deleted — registration failed earlier, or another
            # rescuer claimed us as dead. Recreate so we're discoverable.
            logger.warning(
                "Worker heartbeat row missing, re-registering",
                extra={"worker_id": str(self.worker_id)},
            )
            self._create_heartbeat_row()

    def register_heartbeat(self) -> None:
        try:
            self._create_heartbeat_row()
            self._heartbeat_at = time.time()
            self._heartbeat_registered = True
        except Exception as e:
            # Registration failure is non-fatal — maybe_heartbeat will retry.
            # Until it succeeds, _heartbeat_registered stays False and the run
            # loop won't claim work.
            logger.exception(e)
            logger.warning(
                "Worker heartbeat registration failed; worker will not claim "
                "jobs until a heartbeat row is created",
                extra={"worker_id": str(self.worker_id)},
            )

    def maybe_heartbeat(self) -> None:
        now = time.time()
        if (
            self._heartbeat_registered
            and now - self._heartbeat_at < settings.JOBS_HEARTBEAT_INTERVAL
        ):
            return

        try:
            self._refresh_heartbeat()
            self._heartbeat_at = now
            self._heartbeat_registered = True
        except Exception as e:
            # We don't know if the row exists (the update may have returned 0
            # and the recreate may have raised). Mark unregistered so the run
            # loop stops claiming work until the next tick succeeds. If the
            # DB is unreachable for long enough, our row goes stale and
            # rescue marks our jobs LOST — that's the intended behavior.
            self._heartbeat_registered = False
            logger.exception(e)

    def deregister_heartbeat(self) -> None:
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import JobProcess, WorkerHeartbeat

        try:
            # If any JobProcess rows still reference this worker_id, a
            # bookkeeping error during drain (e.g. future_finished_callback's
            # own convert_to_result raised) left them stranded. Don't delete
            # the heartbeat — let it go stale so rescue can pick them up.
            if JobProcess.query.filter(worker_id=self.worker_id).exists():
                logger.warning(
                    "Worker has remaining JobProcess rows at shutdown; "
                    "leaving heartbeat for rescue to claim",
                    extra={"worker_id": str(self.worker_id)},
                )
                return

            WorkerHeartbeat.query.filter(worker_id=self.worker_id).delete()
        except Exception as e:
            # Best effort. A leftover row will be reclaimed by rescue when its
            # heartbeat goes stale.
            logger.exception(e)

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
                        "Scheduling job",
                        extra={
                            "job_class": result.job_class,
                            "job_queue": result.queue,
                            "job_start_at": result.start_at,
                            "job_schedule": schedule,
                            "concurrency_key": result.concurrency_key,
                        },
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
            "Job worker stats",
            extra={
                "worker_processes": num_proccesses,
                "worker_queues": ",".join(self.queues),
                "jobs_requested": jobs_requested,
                "jobs_processing": jobs_processing,
                "worker_max_processes": self.max_processes,
                "worker_max_jobs_per_process": self.max_jobs_per_process,
            },
        )

    def rescue_job_results(self) -> None:
        """Find any lost or failed jobs on this worker's queues and handle them.

        Hooks are dispatched with maybe_heartbeat() interleaved so a slow or
        large batch of on_aborted hooks can't starve our heartbeat and trigger
        a false-positive LOST from a peer's rescue tick.
        """
        # Lazy import - see _worker_process_initializer() comment for why
        from .models import JobResult, rescue_stale_workers

        # rescue_stale_workers is global, not queue-scoped — a dead worker's
        # heartbeat going stale is a global signal, and partial conversion
        # would strand jobs.
        global_hooks = rescue_stale_workers()
        own_hooks = self._rescue_own_orphans()
        self._dispatch_aborted_hooks(global_hooks + own_hooks)
        JobResult.query.filter(queue__in=self.queues).retry_failed_jobs()

    def _dispatch_aborted_hooks(self, results: list[JobResult]) -> None:
        for result in results:
            self.maybe_heartbeat()
            result.dispatch_aborted_hook()

    def _rescue_own_orphans(self) -> list[JobResult]:
        """Convert any of our own JobProcess rows that aren't tracked by a
        live future to LOST.

        These shouldn't normally exist. The path that creates them: a future
        completes, future_finished_callback runs, but convert_to_result raises
        (transient DB error, peer-rescuer constraint conflict, etc.). The
        exception escapes the callback into concurrent.futures (which logs and
        moves on), _discard_inflight still fires from the second callback, and
        the row is left in the DB with no path back — our heartbeat is fresh
        so rescue_stale_workers won't see it.

        Age threshold avoids racing with newly-claimed rows that haven't been
        added to _inflight_futures yet (microsecond window between
        convert_to_job_process and the dict insert in _run_loop).

        Returns JobResults whose on_aborted hook the caller should dispatch.
        """
        from .models import JobProcess, JobResultStatuses

        with self._inflight_lock:
            inflight_uuids = list(self._inflight_futures.values())

        cutoff = timezone.now() - datetime.timedelta(
            seconds=settings.JOBS_HEARTBEAT_TIMEOUT
        )
        stranded = JobProcess.query.filter(
            worker_id=self.worker_id,
            created_at__lt=cutoff,
        ).exclude(uuid__in=inflight_uuids)

        pending_hooks: list[JobResult] = []
        for orphan in list(stranded):
            try:
                result = orphan.convert_to_result(
                    status=JobResultStatuses.LOST,
                    error="JobProcess stranded — done-callback failed during conversion",
                    fire_hook=False,
                )
            except Exception:
                logger.exception(
                    "Failed to rescue own orphan JobProcess",
                    extra={"job_process_uuid": str(orphan.uuid)},
                )
                continue
            pending_hooks.append(result)
        return pending_hooks


def future_finished_callback(job_process_uuid: str, future: Future) -> None:
    # Lazy import - see _worker_process_initializer() comment for why
    from .models import JobProcess, JobResultStatuses

    if future.cancelled():
        logger.warning("Job cancelled", extra={"job_process_uuid": job_process_uuid})
        try:
            job = JobProcess.query.get(uuid=job_process_uuid)
            job.convert_to_result(status=JobResultStatuses.CANCELLED)
        except JobProcess.DoesNotExist:
            # Job may have already been cleaned up
            pass
    elif exception := future.exception():
        # Process pool may have been killed (OOM/segfault), or process_job
        # itself raised past its outer except (e.g. import failure).
        logger.warning(
            "Job failed",
            extra={"job_process_uuid": job_process_uuid},
            exc_info=exception,
        )
        try:
            job = JobProcess.query.get(uuid=job_process_uuid)
            # If started_at is set, run() was actively executing when the
            # process died — user code may have set up state it expected to
            # tear down. Use LOST so on_aborted fires. If started_at is
            # unset, run() never got to execute (import failure, etc.), so
            # ERRORED with no hook is correct.
            if job.started_at is not None:
                status = JobResultStatuses.LOST
            else:
                status = JobResultStatuses.ERRORED
            job.convert_to_result(
                status=status,
                error="".join(traceback.format_exception(exception)),
            )
        except JobProcess.DoesNotExist:
            # Job may have already been cleaned up
            pass
    else:
        logger.debug("Job finished", extra={"job_process_uuid": job_process_uuid})
        # Orphan check: process_job's outer except-Exception swallows any
        # failure that escapes job.run() (middleware crash, OTel error, DB
        # blip during convert_to_result, etc.). The future completes cleanly
        # but the JobProcess row was never converted, and since our parent
        # is still heartbeating, rescue_stale_workers won't see it as orphaned.
        job = JobProcess.query.filter(uuid=job_process_uuid).first()
        if job is None:
            return
        logger.warning(
            "Job future completed but JobProcess survived; converting to ERRORED",
            extra={"job_process_uuid": job_process_uuid},
        )
        try:
            job.convert_to_result(
                status=JobResultStatuses.ERRORED,
                error="Job future completed without recording a result",
            )
        except Exception:
            # A peer rescuer may have already created a JobResult(LOST) for
            # this row, in which case the unique constraint on
            # JobResult.job_process_uuid trips. Either way, the row is now
            # accounted for — log and move on rather than letting the
            # exception escape into the executor's done-callback machinery.
            logger.exception(
                "Failed to convert orphan JobProcess to ERRORED",
                extra={"job_process_uuid": job_process_uuid},
            )


def process_job(job_process_uuid: str) -> None:
    # Lazy import - see _worker_process_initializer() comment for why
    from .models import JobProcess

    try:
        worker_pid = os.getpid()

        try:
            job_process = JobProcess.query.get(uuid=job_process_uuid)
        except Exception as e:
            # The CONSUMER span inside JobProcess.run() is never reached if
            # the lookup itself fails. Emit one here so the failure has an
            # entry-span home in OTel (e.g. a psycopg transient on this read
            # would otherwise leave only a CLIENT span, which entry-span
            # filtering excludes).
            with tracer.start_as_current_span(
                "process job",
                kind=trace.SpanKind.CONSUMER,
            ) as span:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute(ERROR_TYPE, format_exception_type(e))
            raise

        logger.info(
            "Executing job",
            extra={
                "worker_pid": worker_pid,
                "job_class": job_process.job_class,
                "job_request_uuid": job_process.job_request_uuid,
                "job_priority": job_process.priority,
                "job_source": job_process.source,
                "job_queue": job_process.queue,
            },
        )

        def middleware_chain(job: JobProcess) -> JobResult:
            return job.run()

        for middleware_path in reversed(settings.JOBS_MIDDLEWARE):
            middleware_class = import_string(middleware_path)
            middleware_instance = middleware_class(middleware_chain)
            middleware_chain = middleware_instance.process_job

        job_result = middleware_chain(job_process)

        assert job_result.ended_at is not None
        assert job_result.started_at is not None
        duration = job_result.ended_at - job_result.started_at
        duration = duration.total_seconds()

        if job_result.requested_at and job_result.started_at:
            queue_time = (
                job_result.started_at - job_result.requested_at
            ).total_seconds()
        else:
            queue_time = None

        logger.info(
            "Completed job",
            extra={
                "worker_pid": worker_pid,
                "job_class": job_result.job_class,
                "job_process_uuid": job_result.job_process_uuid,
                "job_request_uuid": job_result.job_request_uuid,
                "job_result_uuid": job_result.uuid,
                "job_priority": job_result.priority,
                "job_source": job_result.source,
                "job_queue": job_result.queue,
                "job_duration": duration,
                "job_queue_time": queue_time,
            },
        )
    except Exception as e:
        # Raising exceptions inside the worker process doesn't
        # seem to be caught/shown anywhere as configured.
        # So we at least log it out here.
        # (A job should catch it's own user-code errors, so this is for library errors)
        logger.exception(e)
    finally:
        return_database_connection()
        gc.collect()
