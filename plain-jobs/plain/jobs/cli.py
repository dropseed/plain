from __future__ import annotations

import datetime
import logging
import signal
from typing import Any

import click

from plain.cli import register_cli
from plain.runtime import settings
from plain.utils import timezone

from .models import JobProcess, JobRequest, JobResult
from .registry import jobs_registry
from .scheduling import load_schedule
from .workers import Worker

logger = logging.getLogger("plain.jobs")


@register_cli("jobs")
@click.group()
def cli() -> None:
    """Background job management"""


@cli.command()
@click.option(
    "queues",
    "--queue",
    default=["default"],
    multiple=True,
    type=str,
    help="Queue to process",
)
@click.option(
    "--max-processes",
    "max_processes",
    default=None,
    type=int,
    envvar="PLAIN_JOBS_WORKER_MAX_PROCESSES",
)
@click.option(
    "--max-jobs-per-process",
    "max_jobs_per_process",
    default=None,
    type=int,
    envvar="PLAIN_JOBS_WORKER_MAX_JOBS_PER_PROCESS",
)
@click.option(
    "--max-pending-per-process",
    "max_pending_per_process",
    default=10,
    type=int,
    envvar="PLAIN_JOBS_WORKER_MAX_PENDING_PER_PROCESS",
)
@click.option(
    "--stats-every",
    "stats_every",
    default=60,
    type=int,
    envvar="PLAIN_JOBS_WORKER_STATS_EVERY",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Watch files and auto-reload worker on changes",
)
def worker(
    queues: tuple[str, ...],
    max_processes: int | None,
    max_jobs_per_process: int | None,
    max_pending_per_process: int,
    stats_every: int,
    reload: bool,
) -> None:
    """Run the job worker"""
    jobs_schedule = load_schedule(settings.JOBS_SCHEDULE)

    if reload:
        from plain.internal.reloader import Reloader

        # Track whether we should continue restarting
        should_restart = {"value": True}
        current_worker = {"instance": None}

        def file_changed(filename: str) -> None:
            if current_worker["instance"]:
                current_worker["instance"].shutdown()

        def signal_shutdown(signalnum: int, _: Any) -> None:
            should_restart["value"] = False
            if current_worker["instance"]:
                current_worker["instance"].shutdown()

        # Allow the worker to be stopped gracefully on SIGTERM/SIGINT
        signal.signal(signal.SIGTERM, signal_shutdown)
        signal.signal(signal.SIGINT, signal_shutdown)

        # Start file watcher once, outside the loop
        reloader = Reloader(callback=file_changed, watch_html=False)
        reloader.start()

        while should_restart["value"]:
            worker = Worker(
                queues=list(queues),
                jobs_schedule=jobs_schedule,
                max_processes=max_processes,
                max_jobs_per_process=max_jobs_per_process,
                max_pending_per_process=max_pending_per_process,
                stats_every=stats_every,
            )
            current_worker["instance"] = worker

            # Start processing jobs (blocks until shutdown)
            worker.run()

    else:
        worker = Worker(
            queues=list(queues),
            jobs_schedule=jobs_schedule,
            max_processes=max_processes,
            max_jobs_per_process=max_jobs_per_process,
            max_pending_per_process=max_pending_per_process,
            stats_every=stats_every,
        )

        def _shutdown(signalnum: int, _: Any) -> None:
            logger.info("Job worker shutdown signal received signalnum=%s", signalnum)
            worker.shutdown()

        # Allow the worker to be stopped gracefully on SIGTERM
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        # Start processing jobs
        worker.run()


@cli.command()
def clear() -> None:
    """Clear completed job results"""
    cutoff = timezone.now() - datetime.timedelta(
        seconds=settings.JOBS_RESULTS_RETENTION
    )
    click.echo(f"Clearing job results created before {cutoff}")
    results = JobResult.query.filter(created_at__lt=cutoff).delete()
    click.echo(f"Deleted {results[0]} jobs")


@cli.command()
def stats() -> None:
    """Show job queue statistics"""
    pending = JobRequest.query.count()
    processing = JobProcess.query.count()

    successful = JobResult.query.successful().count()
    errored = JobResult.query.errored().count()
    lost = JobResult.query.lost().count()

    click.secho(f"Pending: {pending}", bold=True)
    click.secho(f"Processing: {processing}", bold=True)
    click.secho(f"Successful: {successful}", bold=True, fg="green")
    click.secho(f"Errored: {errored}", bold=True, fg="red")
    click.secho(f"Lost: {lost}", bold=True, fg="yellow")


@cli.command()
def purge() -> None:
    """Delete all pending and running jobs"""
    if not click.confirm(
        "Are you sure you want to clear all running and pending jobs? This will delete all current Jobs and JobRequests"
    ):
        return

    deleted = JobRequest.query.all().delete()[0]
    click.echo(f"Deleted {deleted} job requests")

    deleted = JobProcess.query.all().delete()[0]
    click.echo(f"Deleted {deleted} jobs")


@cli.command()
@click.argument("job_class_name", type=str)
def run(job_class_name: str) -> None:
    """Run a job directly without a worker"""
    job = jobs_registry.load_job(job_class_name, {"args": [], "kwargs": {}})
    click.secho("Loaded job: ", bold=True, nl=False)
    print(job)
    job.run()


@cli.command("list")
def list_jobs() -> None:
    """List all registered jobs"""
    for name, job_class in jobs_registry.jobs.items():
        click.secho(f"{name}", bold=True, nl=False)
        # Get description from class docstring
        description = job_class.__doc__.strip() if job_class.__doc__ else ""
        if description:
            click.secho(f": {description}", dim=True)
        else:
            click.echo("")
