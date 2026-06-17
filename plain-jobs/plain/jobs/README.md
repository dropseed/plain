# plain.jobs

**Process background jobs with a database-driven job queue.**

- [Overview](#overview)
- [Local development](#local-development)
- [Job parameters](#job-parameters)
- [Job methods](#job-methods)
- [Scheduled jobs](#scheduled-jobs)
- [Admin interface](#admin-interface)
- [Job history](#job-history)
- [Worker resilience](#worker-resilience)
- [Monitoring](#monitoring)
- [Settings](#settings)
- [FAQs](#faqs)
- [Idempotency](#idempotency)
- [Installation](#installation)

## Overview

Jobs are defined using the [`Job`](./jobs.py#Job) base class and the `run()` method at a minimum.

```python
from plain.jobs import Job, register_job
from plain.email import send_mail


@register_job
class WelcomeUserJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        send_mail(
            subject="Welcome!",
            message=f"Hello from Plain, {self.user}",
            from_email="welcome@plainframework.com",
            recipient_list=[self.user.email],
        )
```

You can then create an instance of the job and call [`run_in_worker()`](./jobs.py#Job.run_in_worker) to enqueue it for a background worker to pick up.

```python
user = User.query.get(id=1)
WelcomeUserJob(user).run_in_worker()
```

Workers are run using the `plain jobs worker` command.

Jobs can be defined in any Python file, but it is suggested to use `app/jobs.py` or `app/{pkg}/jobs.py` as those will be imported automatically so the [`@register_job`](./registry.py#register_job) decorator will fire.

Sync the database after installation:

```bash
plain postgres sync
```

## Local development

In development, you will typically want to run the worker alongside your app with auto-reloading enabled. With [`plain.dev`](/plain-dev/plain/dev/README.md) you can do this by adding it to the `[tool.plain.dev.run]` section of your `pyproject.toml` file.

```toml
# pyproject.toml
[tool.plain.dev.run]
worker = {cmd = "plain jobs worker --reload --stats-every 0 --max-processes 2"}
worker-slow = {cmd = "plain jobs worker --reload --queue slow --stats-every 0 --max-processes 2"}
```

The `--reload` flag will automatically watch `.py` and `.env*` files for changes and restart the worker when changes are detected.

## Job parameters

When calling `run_in_worker()`, you can specify several parameters to control job execution:

```python
job.run_in_worker(
    queue="slow",  # Target a specific queue (default: "default")
    delay=60,  # Delay in seconds (or timedelta/datetime)
    priority=10,  # Higher numbers run first (default: 0, use negatives for lower priority)
    retries=3,  # Number of retry attempts (default: 0)
    concurrency_key="user-123-welcome",  # Identifier for grouping/deduplication
)
```

For more advanced parameter options, see [`Job.run_in_worker()`](./jobs.py#Job.run_in_worker).

## Job methods

The [`Job`](./jobs.py#Job) base class provides several methods you can override to customize behavior:

```python
class MyJob(Job):
    def run(self):
        # Required: The main job logic
        pass

    # Defaults (can be overridden in run_in_worker)
    def default_queue(self) -> str:
        return "default"

    def default_priority(self) -> int:
        # Higher numbers run first: 10 > 5 > 0 > -5 > -10
        return 0

    def default_retries(self) -> int:
        return 0

    def default_concurrency_key(self) -> str:
        # Identifier for grouping/deduplication
        return ""

    # Computed values
    def calculate_retry_delay(self, attempt: int) -> int:
        # Delay in seconds before retry (attempt starts at 1)
        return 0

    # Hooks
    def should_enqueue(self, concurrency_key: str) -> bool:
        # Called before enqueueing - return False to skip
        # Use for concurrency limits, rate limits, etc.
        return True

    def on_aborted(self, result: JobResult) -> None:
        # Called when this job's process was terminated externally before
        # run() could complete (status=LOST or status=CANCELLED).
        # Use this to reconcile domain state that run()'s try/finally would
        # have released, since try/finally did not execute.
        pass
```

## Scheduled jobs

Schedules are configured via the `JOBS_SCHEDULE` setting as a list of `(job, schedule)` tuples. The job can be a dotted path to a `Job` subclass (or a `"cmd:<shell command>"` string), and the schedule can be a cron expression string or a [`Schedule`](./scheduling.py#Schedule) instance:

```python
# app/settings.py
JOBS_SCHEDULE = [
    ("app.reports.jobs.DailyReportJob", "0 9 * * *"),  # Every day at 9 AM
    ("cmd:./scripts/cleanup", "@daily"),
]
```

Cron expressions support standard syntax and special strings:

- `@yearly` or `@annually` - Run once a year
- `@monthly` - Run once a month
- `@weekly` - Run once a week
- `@daily` or `@midnight` - Run once a day
- `@hourly` - Run once an hour

Day-of-week follows standard cron numbering: **`0` (or `7`) is Sunday** through `6` for Saturday, and three-letter names (`SUN`–`SAT`, `JAN`–`DEC`) are accepted. Also as in standard cron, when **both** the day-of-month and day-of-week fields are restricted, the job runs whenever **either** matches — so `30 4 1,15 * 5` runs at 4:30 AM on the 1st and 15th _plus_ every Friday.

For custom schedules, see [`Schedule`](./scheduling.py#Schedule), which takes the same fields as keyword arguments. Its day-of-month and day-of-week combine with plain AND (both must match); pass `combine_days_with_or=True` for the cron OR behavior.

## Admin interface

The jobs package includes admin views for monitoring jobs under the "Jobs" section. The admin interface provides:

- **Requests**: View pending jobs in the queue
- **Processes**: Monitor currently running jobs
- **Results**: Review completed and failed job history

Dashboard cards show at-a-glance statistics for successful, errored, lost, and retried jobs.

## Job history

Job execution history is stored in the [`JobResult`](./models.py#JobResult) model. This includes:

- Job class and parameters
- Start and end times
- Success/failure status
- Error messages and tracebacks for failed jobs
- Worker information

See [Settings](#settings) for configuring job retention and timeouts.

## Worker resilience

Each worker process registers itself in a [`WorkerHeartbeat`](./models.py#WorkerHeartbeat) row at startup, bumps `last_heartbeat_at` every `JOBS_HEARTBEAT_INTERVAL` seconds while running, and deletes the row on clean shutdown. Every `JobProcess` is stamped with the picking worker's `worker_id`, so when a heartbeat goes stale (older than `JOBS_HEARTBEAT_TIMEOUT`), the next worker's rescue tick can find the dead worker's in-flight jobs and convert them to `JobResult(status=LOST)`.

This means a worker killed mid-run (Heroku deploy SIGKILL, OOM, host crash) gets detected within a few minutes — independent of how long any individual job legitimately runs. A long-running job is safe as long as its worker keeps heartbeating.

### Reacting to abortions

Override [`Job.on_aborted(result)`](./jobs.py#Job.on_aborted) to react when a job's process is terminated externally:

```python
@register_job
class GenerateReportJob(Job):
    def __init__(self, report_id):
        self.report_id = report_id

    def run(self):
        report = Report.query.get(id=self.report_id)
        report.status = "running"
        report.update()
        # ...do the work...
        report.status = "done"
        report.update()

    def on_aborted(self, result):
        # The worker was killed mid-run; run()'s cleanup never executed.
        # Flip the report out of the limbo state.
        Report.query.filter(id=self.report_id).update(
            status="failed", error="worker terminated"
        )
```

The hook fires for terminal statuses that `run()` itself could not observe — `LOST` (process killed) and `CANCELLED` (future cancelled before execution). It does **not** fire for `SUCCESSFUL` or `ERRORED`, which `run()` can handle directly via normal control flow.

The Job instance is reconstructed from stored parameters; no in-memory state from the original run is preserved. Exceptions raised by the hook are caught and logged so they cannot block the result from being recorded.

If your job has retries configured, `on_aborted` fires when the JobProcess transitions to LOST/CANCELLED — _before_ any retry runs. Apps that only want to react after retries are exhausted should check `result.retries == result.retry_attempt`.

## Monitoring

Workers report statistics and can be monitored using the `--stats-every` option:

```bash
# Report stats every 60 seconds
plain jobs worker --stats-every 60
```

The worker integrates with OpenTelemetry for distributed tracing. Spans are created for:

- Job scheduling (`run_in_worker`) — emits a `send {queue}` PRODUCER span with the OTel `messaging.*` semconv attributes
- Job execution — emits a `process {queue}` CONSUMER span linked back to the originating send span
- Job completion/failure — recorded as the span's status and `error.type` attribute on failure

Jobs are linked to the originating trace context, allowing you to follow jobs initiated from web requests.

Messaging metrics:

- `messaging.client.sent.messages` — counter incremented for each enqueue
- `messaging.client.consumed.messages` — counter incremented for every terminal `JobResult`. Carries a `plain.jobs.outcome` attribute (`successful`, `errored`, `lost`, `cancelled`, `deferred`) so dashboards can split throughput by outcome.
- `messaging.client.operation.duration` — histogram of enqueue/process durations
- `plain.jobs.queue.wait.duration` — histogram of how long a job waited in queue before a worker picked it up

Per-worker observable gauges (queryable per `messaging.destination.name` where applicable):

- `plain.jobs.worker.processes` — OS processes spawned by this worker
- `plain.jobs.queue.depth` — pending `JobRequest`s ready to run
- `plain.jobs.queue.scheduled` — `JobRequest`s with `start_at` in the future
- `plain.jobs.queue.oldest.age` — age in seconds of the oldest ready-to-run `JobRequest`
- `plain.jobs.running` — `JobProcess` rows currently running

Worker-liveness gauge (global, no per-queue dimension):

- `plain.jobs.workers` — `WorkerHeartbeat` row count, split by a `plain.jobs.worker.state` attribute taking `active` (within `JOBS_HEARTBEAT_TIMEOUT`) or `stale` (past it, eligible for rescue on the next tick)

Two contract details to be aware of:

- **Successful enqueues record metrics on transaction commit.** If you call `run_in_worker` inside a transaction that later rolls back, the message was never actually persisted — so the counter and histogram do not fire. This matches the OTel semconv: "MUST NOT count messages that were created but haven't yet been sent." Failed enqueues record immediately so transient errors are still visible.
- **Skipped enqueues are visible in spans, not in metrics.** When `should_enqueue` returns `False` (e.g., a concurrency-key collision), the span gets `job.enqueue.skipped=True` but no metric is recorded — there was no send to count.
- **Observable gauges emit once per worker process.** When two workers cover the same queue, the per-queue gauges emit identical values from each. `plain.jobs.workers` is global (no per-queue dimension) and likewise emits the full table count from every worker. Aggregate these gauges with `last_value`/`max`, never `sum`.

## Settings

| Setting                               | Default           |
| ------------------------------------- | ----------------- |
| `JOBS_RESULTS_RETENTION`              | `604800` (7 days) |
| `JOBS_HEARTBEAT_INTERVAL`             | `60` (1 minute)   |
| `JOBS_HEARTBEAT_TIMEOUT`              | `300` (5 minutes) |
| `JOBS_MIDDLEWARE`                     | `[...]`           |
| `JOBS_SCHEDULE`                       | `[]`              |
| `JOBS_WORKER_MAX_PROCESSES`           | `None`            |
| `JOBS_WORKER_MAX_JOBS_PER_PROCESS`    | `None`            |
| `JOBS_WORKER_MAX_PENDING_PER_PROCESS` | `10`              |
| `JOBS_WORKER_STATS_EVERY`             | `60`              |

The `JOBS_WORKER_*` settings configure the `plain jobs worker` command and can also be overridden via CLI flags (e.g. `--max-processes`).

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I ensure only one job runs at a time?

Set a `concurrency_key` to automatically enforce uniqueness - only one job with the same key can be pending or processing:

```python
from plain.jobs import Job, register_job

@register_job
class ProcessUserJob(Job):
    def __init__(self, user_id):
        self.user_id = user_id

    def default_concurrency_key(self):
        return f"user-{self.user_id}"

    def run(self):
        process_user(self.user_id)

# Usage
ProcessUserJob(123).run_in_worker()  # Enqueued
ProcessUserJob(123).run_in_worker()  # Returns None (blocked - job already pending/processing)
```

Alternatively, pass `concurrency_key` as a parameter to `run_in_worker()` instead of overriding the method.

#### How do I implement custom concurrency limits?

Use the `should_enqueue()` hook to implement custom concurrency control:

```python
class ProcessUserDataJob(Job):
    def __init__(self, user_id):
        self.user_id = user_id

    def default_concurrency_key(self):
        return f"user-{self.user_id}"

    def should_enqueue(self, concurrency_key):
        # Only allow 1 job per user at a time
        processing = self.get_processing_jobs(concurrency_key).count()
        pending = self.get_requested_jobs(concurrency_key).count()
        return processing == 0 and pending == 0
```

For more patterns like rate limiting and global limits, see [`should_enqueue()`](./jobs.py#should_enqueue) in the source code.

#### How are race conditions prevented?

Plain uses PostgreSQL's [advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS) to ensure `should_enqueue()` checks are atomic with job creation. The lock is acquired during the transaction and automatically released when the transaction completes. This eliminates race conditions where multiple threads might simultaneously pass the `should_enqueue()` check.

For custom locking behavior (Redis, etc.), override [`get_enqueue_lock()`](./locks.py#get_enqueue_lock).

#### Can I run multiple workers?

Yes, you can run multiple worker processes:

```bash
plain jobs worker --max-processes 4
```

Or run workers for specific queues:

```bash
plain jobs worker --queue slow --max-processes 2
```

#### How do I handle job failures?

Set the number of retries and implement retry delays:

```python
class MyJob(Job):
    def default_retries(self):
        return 3

    def calculate_retry_delay(self, attempt):
        # Exponential backoff: 1s, 2s, 4s
        return 2 ** (attempt - 1)
```

## Idempotency

Jobs may retry on failure, so design them so re-execution is safe.

```python
# Bad — sends duplicate emails on retry
@register_job
class WelcomeUserJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        send_welcome_email(self.user)

# Good — check before acting
@register_job
class WelcomeUserJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        if not self.user.welcome_email_sent:
            send_welcome_email(self.user)
            self.user.welcome_email_sent = True
            self.user.update()
```

## Installation

Install the `plain.jobs` package from [PyPI](https://pypi.org/project/plain.jobs/):

```bash
uv add plain.jobs
```

Add to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.jobs",
]
```
