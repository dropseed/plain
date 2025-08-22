# plain.worker

**Process background jobs with a database-driven worker.**

- [Overview](#overview)
- [Local development](#local-development)
- [Job parameters](#job-parameters)
- [Job methods](#job-methods)
- [Scheduled jobs](#scheduled-jobs)
- [Admin interface](#admin-interface)
- [Job history](#job-history)
- [Monitoring](#monitoring)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Jobs are defined using the [`Job`](./jobs.py#Job) base class and the `run()` method at a minimum.

```python
from plain.worker import Job, register_job
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
user = User.objects.get(id=1)
WelcomeUserJob(user).run_in_worker()
```

Workers are run using the `plain worker run` command.

Jobs can be defined in any Python file, but it is suggested to use `app/jobs.py` or `app/{pkg}/jobs.py` as those will be imported automatically so the [`@register_job`](./registry.py#register_job) decorator will fire.

Run database migrations after installation:

```bash
plain migrate
```

## Local development

In development, you will typically want to run the worker alongside your app. With [`plain.dev`](/plain-dev/plain/dev/README.md) you can do this by adding it to the `[tool.plain.dev.run]` section of your `pyproject.toml` file. Currently, you will need to use something like [watchfiles](https://pypi.org/project/watchfiles/) to add auto-reloading to the worker.

```toml
# pyproject.toml
[tool.plain.dev.run]
worker = {cmd = "watchfiles --filter python \"plain worker run --stats-every 0 --max-processes 2\" ."}
worker-slow = {cmd = "watchfiles --filter python \"plain worker run --queue slow --stats-every 0 --max-processes 2\" ."}
```

## Job parameters

When calling `run_in_worker()`, you can specify several parameters to control job execution:

```python
job.run_in_worker(
    queue="slow",  # Target a specific queue (default: "default")
    delay=60,  # Delay in seconds (or timedelta/datetime)
    priority=10,  # Higher numbers run first (default: 0, use negatives for lower priority)
    retries=3,  # Number of retry attempts (default: 0)
    unique_key="user-123-welcome",  # Prevent duplicate jobs
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

    def get_queue(self) -> str:
        # Specify the default queue for this job type
        return "default"

    def get_priority(self) -> int:
        # Set the default priority
        # Higher numbers run first: 10 > 5 > 0 > -5 > -10
        # Use positive numbers for high priority, negative for low priority
        return 0

    def get_retries(self) -> int:
        # Number of retry attempts on failure
        return 0

    def get_retry_delay(self, attempt: int) -> int:
        # Delay in seconds before retry (attempt starts at 1)
        return 0

    def get_unique_key(self) -> str:
        # Return a key to prevent duplicate jobs
        return ""
```

## Scheduled jobs

You can schedule jobs to run at specific times using the [`Schedule`](./scheduling.py#Schedule) class:

```python
from plain.worker import Job, register_job
from plain.worker.scheduling import Schedule

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

The worker package includes admin views for monitoring jobs. The admin interface provides:

- **Job Requests**: View pending jobs in the queue
- **Jobs**: Monitor currently running jobs
- **Job Results**: Review completed and failed job history

Dashboard cards show at-a-glance statistics for successful and errored jobs.

## Job history

Job execution history is stored in the [`JobResult`](./models.py#JobResult) model. This includes:

- Job class and parameters
- Start and end times
- Success/failure status
- Error messages and tracebacks for failed jobs
- Worker information

History retention can be configured in your settings:

```python
# app/settings.py
WORKER_JOB_HISTORY_DAYS = 30
```

## Monitoring

Workers report statistics and can be monitored using the `--stats-every` option:

```bash
# Report stats every 60 seconds
plain worker run --stats-every 60
```

The worker integrates with OpenTelemetry for distributed tracing. Spans are created for:

- Job scheduling (`run_in_worker`)
- Job execution
- Job completion/failure

Jobs can be linked to the originating trace context, allowing you to track jobs initiated from web requests.

## FAQs

#### How do I ensure a job only runs once?

Return a unique key from the `get_unique_key()` method:

```python
class ProcessUserDataJob(Job):
    def __init__(self, user_id):
        self.user_id = user_id

    def get_unique_key(self):
        return f"process-user-{self.user_id}"
```

#### Can I run multiple workers?

Yes, you can run multiple worker processes:

```bash
plain worker run --max-processes 4
```

Or run workers for specific queues:

```bash
plain worker run --queue slow --max-processes 2
```

#### How do I handle job failures?

Set the number of retries and implement retry delays:

```python
class MyJob(Job):
    def get_retries(self):
        return 3

    def get_retry_delay(self, attempt):
        # Exponential backoff: 1s, 2s, 4s
        return 2 ** (attempt - 1)
```

## Installation

Install the `plain.worker` package from [PyPI](https://pypi.org/project/plain.worker/):

```bash
uv add plain.worker
```

Add to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.worker",
]
```
