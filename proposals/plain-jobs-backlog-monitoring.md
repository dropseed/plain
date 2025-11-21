# plain-jobs: Worker backlog monitoring

- Add backlog threshold checking to existing worker stats logging
- Configurable thresholds via `JOBS_BACKLOG_WARNING` and `JOBS_BACKLOG_CRITICAL`
- Warnings logged periodically (default every 60s via `--stats-every`)
- Helps detect when workers aren't keeping up with job volume

## Configuration

Add to `plain/plain/jobs/default_settings.py`:

```python
JOBS_BACKLOG_WARNING = None  # Optional: log warning when backlog exceeds this
JOBS_BACKLOG_CRITICAL = None  # Optional: log critical when backlog exceeds this
```

Users can configure in their settings:

```python
# app/settings.py
JOBS_BACKLOG_WARNING = 500
JOBS_BACKLOG_CRITICAL = 1000
```

## Implementation

Extend the existing `Worker.log_stats()` method in `workers.py:239`:

```python
def log_stats(self) -> None:
    from .models import JobProcess, JobRequest

    try:
        num_proccesses = len(self.executor._processes)
    except (AttributeError, TypeError):
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

    # NEW: Check backlog thresholds
    self.check_backlog_thresholds(jobs_requested, jobs_processing)

def check_backlog_thresholds(self, jobs_requested: int, jobs_processing: int) -> None:
    """Check if job backlog exceeds warning/critical thresholds"""
    critical = getattr(settings, 'JOBS_BACKLOG_CRITICAL', None)
    warning = getattr(settings, 'JOBS_BACKLOG_WARNING', None)

    if not critical and not warning:
        return

    jobs_backlog = jobs_requested + jobs_processing

    if critical and jobs_backlog >= critical:
        logger.critical(
            'Job backlog critical worker_queues="%s" jobs_backlog=%s jobs_requested=%s jobs_processing=%s threshold=%s',
            ",".join(self.queues),
            jobs_backlog,
            jobs_requested,
            jobs_processing,
            critical,
        )
    elif warning and jobs_backlog >= warning:
        logger.warning(
            'Job backlog warning worker_queues="%s" jobs_backlog=%s jobs_requested=%s jobs_processing=%s threshold=%s',
            ",".join(self.queues),
            jobs_backlog,
            jobs_requested,
            jobs_processing,
            warning,
        )
```

## Benefits

- Leverages existing stats logging infrastructure (`--stats-every`, default 60s)
- Production visibility through worker logs and monitoring tools (Datadog, Sentry, etc.)
- Minimal implementation - just extend existing `log_stats()` method
- Follows existing Plain jobs logging pattern (structured k=v format)
- Simple configuration - just two integer settings
- Opt-in via settings - no impact if not configured

## Notes

- Uses same logging format as other worker stats: `job_queue="default" jobs_requested=1500 threshold=1000`
- Runs whenever `log_stats()` runs (controlled by `--stats-every` flag)
- Can enable more frequent checks by passing `--stats-every=30` to worker command
- Could also add a one-time check on worker startup if desired
