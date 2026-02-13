---
paths:
  - "**/jobs.py"
---

# Background Jobs

- Keep jobs idempotent — they may retry on failure, so re-execution must be safe
- Offload slow work (email, API calls, file processing) to jobs — don't block HTTP responses
- Use `concurrency_key` to prevent duplicate jobs for the same resource

Run `uv run plain docs jobs` for full documentation.
