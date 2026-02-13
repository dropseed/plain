# plain.jobs

**Process background jobs with a database-driven job queue.**

- [Overview](#overview)
- [Local development](#local-development)
- [Job parameters](#job-parameters)
- [Job methods](#job-methods)
- [Scheduled jobs](#scheduled-jobs)
- [Admin interface](#admin-interface)
- [Job history](#job-history)
- [Monitoring](#monitoring)
- [Settings](#settings)
- [FAQs](#faqs)
- [Best practices](#best-practices)
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

Run database migrations after installation:

```bash
plain migrate
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
```

## Scheduled jobs

You can schedule jobs to run at specific times using the [`Schedule`](./scheduling.py#Schedule) class:

```python
from plain.jobs import Job, register_job
from plain.jobs.scheduling import Schedule

@register_job
class DailyReportJob(Job):
    schedule = Schedule.from_cron("0 9 * * *")  # Every day at 9 AM

    def run(self):
        # Generate daily report
        pass
```

The `Schedule` class supports standard cron syntax and special strings:

- `@yearly` or `@annually` - Run once a year
- `@monthly` - Run once a month
- `@weekly` - Run once a week
- `@daily` or `@midnight` - Run once a day
- `@hourly` - Run once an hour

For custom schedules, see [`Schedule`](./scheduling.py#Schedule).

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

## Monitoring

Workers report statistics and can be monitored using the `--stats-every` option:

```bash
# Report stats every 60 seconds
plain jobs worker --stats-every 60
```

The worker integrates with OpenTelemetry for distributed tracing. Spans are created for:

- Job scheduling (`run_in_worker`)
- Job execution
- Job completion/failure

Jobs can be linked to the originating trace context, allowing you to track jobs initiated from web requests.

## Settings

| Setting                  | Default           | Env var                        |
| ------------------------ | ----------------- | ------------------------------ |
| `JOBS_RESULTS_RETENTION` | `604800` (7 days) | `PLAIN_JOBS_RESULTS_RETENTION` |
| `JOBS_TIMEOUT`           | `86400` (1 day)   | `PLAIN_JOBS_TIMEOUT`           |
| `JOBS_MIDDLEWARE`        | `[...]`           | `PLAIN_JOBS_MIDDLEWARE`        |
| `JOBS_SCHEDULE`          | `[]`              | `PLAIN_JOBS_SCHEDULE`          |

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

On **PostgreSQL**, plain-jobs uses [advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS) to ensure `should_enqueue()` checks are atomic with job creation. The lock is acquired during the transaction and automatically released when the transaction completes. This eliminates race conditions where multiple threads might simultaneously pass the `should_enqueue()` check.

On **SQLite and MySQL**, advisory locks are not available, so a small race condition window exists between checking and creating jobs. For production deployments requiring strict concurrency guarantees, **we recommend PostgreSQL**.

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

## Best practices

### Offload slow work to jobs

Email, external API calls, and file processing should not block the HTTP response. Queue the job and respond immediately.

```python
# Bad — user waits for email to send
def post(self):
    send_welcome_email(user)
    return Response(...)

# Good — queue and respond immediately
def post(self):
    WelcomeUserJob(user).run_in_worker()
    return Response(...)
```

### Keep jobs idempotent

Jobs may retry on failure. Design them so re-execution is safe.

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
            self.user.save()
```

### Always use `@register_job`

Jobs must be decorated with `@register_job` so the worker can discover them.

```python
# Bad — worker can't find this job
class MyJob(Job):
    def run(self):
        ...

# Good
@register_job
class MyJob(Job):
    def run(self):
        ...
```

### Use `run_in_worker()` to enqueue jobs

Call `run_in_worker()` on a job instance to send it to the background queue.

```python
from plain.jobs import Job, register_job

@register_job
class ProcessDataJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        process(self.user)

# Enqueue with options
ProcessDataJob(user).run_in_worker(queue="slow", retries=3, priority=10)
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
