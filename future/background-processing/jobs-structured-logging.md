---
related:
  - preflight-log-warnings
---

# Convert jobs worker to structured context logging

## Problem

The jobs worker manually formats key=value pairs in log message strings:

```python
logger.info(
    'Executing job worker_pid=%s job_class=%s job_request_uuid=%s ...',
    worker_pid, job_process.job_class, job_process.job_request_uuid, ...
)
```

This bypasses the structured logging system — context data isn't available to `KeyValueFormatter` or `JSONFormatter`, so JSON output still gets a flat string instead of discrete fields.

## Proposal

Use `extra={"context": {...}}` on the standard `plain.jobs` logger:

```python
logger.info("Executing job", extra={"context": {
    "worker_pid": worker_pid,
    "job_class": job_process.job_class,
    "job_request_uuid": job_process.job_request_uuid,
    "job_priority": job_process.priority,
    "job_source": job_process.source,
    "job_queue": job_process.queue,
}})
```

The formatters already check `hasattr(record, "context")` — no formatter changes needed. The `plain.jobs` logger just needs to be configured with the same formatter as `app_logger` (see `configure_logging` in `plain/logs/configure.py`).

Applies to: `process_job`, `future_finished_callback`, `log_stats`, `maybe_schedule_jobs`, and startup log in `run()`.
