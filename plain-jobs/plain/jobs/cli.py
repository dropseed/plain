from __future__ import annotations

import datetime
import logging
import signal
from typing import Any

import click

from plain.cli import SettingOption, register_cli
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
    type=int,
    cls=SettingOption,
    setting="JOBS_WORKER_MAX_PROCESSES",
)
@click.option(
    "--max-jobs-per-process",
    "max_jobs_per_process",
    type=int,
    cls=SettingOption,
    setting="JOBS_WORKER_MAX_JOBS_PER_PROCESS",
)
@click.option(
    "--max-pending-per-process",
    "max_pending_per_process",
    type=int,
    cls=SettingOption,
    setting="JOBS_WORKER_MAX_PENDING_PER_PROCESS",
)
@click.option(
    "--stats-every",
    "stats_every",
    type=int,
    cls=SettingOption,
    setting="JOBS_WORKER_STATS_EVERY",
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

    worker_kwargs = {
        "queues": list(queues),
        "jobs_schedule": jobs_schedule,
        "max_processes": max_processes,
        "max_jobs_per_process": max_jobs_per_process,
        "max_pending_per_process": max_pending_per_process,
        "stats_every": stats_every,
    }

    if reload:
        _run_with_reload(worker_kwargs)
    else:
        _run_once(worker_kwargs)


def _run_with_reload(worker_kwargs: dict[str, Any]) -> None:
    from plain.internal.reloader import Reloader

    should_restart = {"value": True}
    current_worker: dict[str, Worker | None] = {"instance": None}

    def file_changed(filename: str) -> None:
        if current_worker["instance"]:
            current_worker["instance"].shutdown()

    def signal_shutdown(signalnum: int, _: Any) -> None:
        should_restart["value"] = False
        if current_worker["instance"]:
            current_worker["instance"].shutdown()

    signal.signal(signal.SIGTERM, signal_shutdown)
    signal.signal(signal.SIGINT, signal_shutdown)

    reloader = Reloader(callback=file_changed, watch_html=False)
    reloader.start()

    while should_restart["value"]:
        w = Worker(**worker_kwargs)
        current_worker["instance"] = w
        w.run()


def _run_once(worker_kwargs: dict[str, Any]) -> None:
    w = Worker(**worker_kwargs)

    def _shutdown(signalnum: int, _: Any) -> None:
        logger.info("Job worker shutdown signal received signalnum=%s", signalnum)
        w.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    w.run()


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
        click.secho(name, bold=True, nl=False)
        description = job_class.__doc__.strip() if job_class.__doc__ else ""
        if description:
            click.secho(f": {description}", dim=True)
        else:
            click.echo("")
