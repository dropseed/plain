---
paths:
  - "**/jobs.py"
---

# Background Jobs

## Writing Jobs

- Always decorate job classes with `@register_job` — the worker cannot discover unregistered jobs
- Implement the `run()` method for job logic
- Call `run_in_worker()` on an instance to enqueue it (supports `queue`, `retries`, `priority`, `delay`, `concurrency_key`)
- Define jobs in `app/jobs.py` or `app/{pkg}/jobs.py` for automatic import

## Best Practices

- Offload slow work (email, API calls, file processing) to jobs — don't block HTTP responses
- Keep jobs idempotent — they may retry on failure, so re-execution must be safe
- Use `concurrency_key` to prevent duplicate jobs for the same resource
- Set `default_retries()` and `calculate_retry_delay()` for jobs that can fail transiently

Run `uv run plain docs jobs --section "best practices"` for full patterns with code examples.

## Scheduled Jobs

- Set `schedule = Schedule.from_cron("...")` on a job class for recurring execution
- Supports standard cron syntax and shortcuts (`@daily`, `@hourly`, etc.)

Run `uv run plain docs jobs --section "scheduled jobs"` for details.
