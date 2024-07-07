import datetime
import logging
import signal

import click

from plain.runtime import settings
from plain.utils import timezone

from .jobs import load_job
from .models import Job, JobRequest, JobResult
from .scheduling import load_schedule
from .workers import Worker

logger = logging.getLogger("plain.worker")


@click.group()
def cli():
    pass


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
    envvar="PLAIN_JOBS_MAX_PROCESSES",
)
@click.option(
    "--max-jobs-per-process",
    "max_jobs_per_process",
    default=None,
    type=int,
    envvar="PLAIN_JOBS_MAX_JOBS_PER_PROCESS",
)
@click.option(
    "--max-pending-per-process",
    "max_pending_per_process",
    default=10,
    type=int,
    envvar="PLAIN_JOBS_MAX_PENDING_PER_PROCESS",
)
@click.option(
    "--stats-every",
    "stats_every",
    default=60,
    type=int,
    envvar="PLAIN_JOBS_STATS_EVERY",
)
def run(
    queues, max_processes, max_jobs_per_process, max_pending_per_process, stats_every
):
    jobs_schedule = load_schedule(settings.WORKER_JOBS_SCHEDULE)

    worker = Worker(
        queues=queues,
        jobs_schedule=jobs_schedule,
        max_processes=max_processes,
        max_jobs_per_process=max_jobs_per_process,
        max_pending_per_process=max_pending_per_process,
        stats_every=stats_every,
    )

    def _shutdown(signalnum, _):
        logger.info("Job worker shutdown signal received signalnum=%s", signalnum)
        worker.shutdown()

    # Allow the worker to be stopped gracefully on SIGTERM
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Start processing jobs
    worker.run()


@cli.command()
def clear_completed():
    """Clear all completed job results in all queues."""
    cutoff = timezone.now() - datetime.timedelta(
        seconds=settings.WORKER_JOBS_CLEARABLE_AFTER
    )
    click.echo(f"Clearing job results created before {cutoff}")
    results = JobResult.objects.filter(created_at__lt=cutoff).delete()
    click.echo(f"Deleted {results[0]} jobs")


@cli.command()
def stats():
    """Stats across all queues."""
    pending = JobRequest.objects.count()
    processing = Job.objects.count()

    successful = JobResult.objects.successful().count()
    errored = JobResult.objects.errored().count()
    lost = JobResult.objects.lost().count()

    click.secho(f"Pending: {pending}", bold=True)
    click.secho(f"Processing: {processing}", bold=True)
    click.secho(f"Successful: {successful}", bold=True, fg="green")
    click.secho(f"Errored: {errored}", bold=True, fg="red")
    click.secho(f"Lost: {lost}", bold=True, fg="yellow")


@cli.command()
def purge_processing():
    """Delete all running and pending jobs regardless of queue."""
    if not click.confirm(
        "Are you sure you want to clear all running and pending jobs? This will delete all current Jobs and JobRequests"
    ):
        return

    deleted = JobRequest.objects.all().delete()[0]
    click.echo(f"Deleted {deleted} job requests")

    deleted = Job.objects.all().delete()[0]
    click.echo(f"Deleted {deleted} jobs")


@cli.command()
@click.argument("job_class", type=str)
def run_job(job_class):
    """Run a job class directly (and not using a worker)."""
    job = load_job(job_class, {"args": [], "kwargs": {}})
    click.secho("Loaded job: ", bold=True, nl=False)
    print(job)
    job.run()
