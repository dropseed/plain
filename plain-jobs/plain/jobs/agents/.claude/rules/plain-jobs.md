---
paths:
  - "**/jobs.py"
---

# Background Jobs

- Keep jobs idempotent — they may retry on failure, so re-execution must be safe
- Offload slow work (email, API calls, file processing) to jobs — don't block HTTP responses
- Use `concurrency_key` to prevent duplicate jobs for the same resource
- Override `Job.on_aborted(result)` to clean up domain state when a job's process is terminated mid-run (status LOST or CANCELLED) — `run()`'s `try/finally` does not execute in that case
- Schedule recurring jobs with the `JOBS_SCHEDULE` setting — slots fire via a database ledger, so removing an entry just stops it (remove the entry when deleting a job class). `plain preflight` validates the schedule config

Run `uv run plain docs jobs` for full documentation.
