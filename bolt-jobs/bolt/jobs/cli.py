import datetime
import logging
import signal

import click

from bolt.runtime import settings
from bolt.utils import timezone

from .models import Job, JobRequest, JobResult
from .workers import Worker

logger = logging.getLogger("bolt.jobs")


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--max-processes",
    "max_processes",
    default=None,
    type=int,
    envvar="BOLT_JOBS_MAX_PROCESSES",
)
@click.option(
    "--max-jobs-per-process",
    "max_jobs_per_process",
    default=None,
    type=int,
    envvar="BOLT_JOBS_MAX_JOBS_PER_PROCESS",
)
@click.option(
    "--stats-every",
    "stats_every",
    default=60,
    type=int,
    envvar="BOLT_JOBS_STATS_EVERY",
)
def worker(max_processes, max_jobs_per_process, stats_every):
    worker = Worker(
        max_processes=max_processes,
        max_jobs_per_process=max_jobs_per_process,
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
    cutoff = timezone.now() - datetime.timedelta(seconds=settings.JOBS_CLEARABLE_AFTER)
    click.echo(f"Clearing jobs finished before {cutoff}")
    results = (
        JobResult.objects.exclude(ended_at__isnull=True)
        .filter(ended_at__lt=cutoff)
        .delete()
    )
    click.echo(f"Deleted {results[0]} jobs")


@cli.command()
def stats():
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
