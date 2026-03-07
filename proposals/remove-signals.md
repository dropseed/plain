---
packages:
- plain.signals
- plain-models
- plain-jobs
related:
- fix-async-view-thread-affinity
- fix-request-finished-streaming
---

# Remove signals from Plain

## Problem

The signals system (`request_started`, `request_finished`) causes problems:

1. **Threading fragility** — The handler must ensure signals fire on the correct thread because `DatabaseConnection` uses `threading.local()`. This constraint leaked into the async view design (two executor calls just to keep signals on the right thread).

2. **Implicit coupling** — `plain-models` silently hooks into the request lifecycle at import time via `signals.request_started.connect(...)`. The handler has no idea what's listening or what those listeners need.

3. **Overkill** — The `Signal` class has weak references, sender filtering, dispatch UIDs, `send_robust()`, thread-safe locking. All of it serves two function calls in one package (`plain-models`).

## Current usage

The **entire** signals system is just `request_started` and `request_finished`. No other signal types exist.

### Senders (2 places)

- `plain/internal/handlers/base.py` — sends both on request start/finish
- `plain-jobs/workers.py` — sends both around job execution

### Receivers (2 functions, both in `plain-models`)

- `reset_queries()` on `request_started` — clears debug query log
- `close_old_connections()` on `request_started` and `request_finished` — closes stale/broken DB connections

## Decision

### HTTP: DatabaseConnectionMiddleware

Replace signals with a `DatabaseConnectionMiddleware` that users add to `settings.MIDDLEWARE`, just like `SessionMiddleware`:

```python
class DatabaseConnectionMiddleware(HttpMiddleware):
    def before_request(self, request):
        if db_connection.has_connection():
            db_connection.queries_log.clear()
            db_connection.close_if_unusable_or_obsolete()
        return None

    def after_response(self, request, response):
        if db_connection.has_connection():
            db_connection.close_if_unusable_or_obsolete()
        return response
```

The `/plain-install` skill adds it to `MIDDLEWARE` when installing `plain-models`. Users can see it, reorder it, understand it. No magic registration.

### Jobs: direct calls

`plain-jobs` already hard-depends on `plain-models` (jobs are stored in the DB). Replace the `request_started.send()` / `request_finished.send()` calls in `process_job()` with direct calls to `reset_queries()` and `close_old_connections()`.

### Delete plain.signals

Remove the module entirely. No deprecation period — the upgrade agent can handle any third-party code that was using it (unlikely, since only `plain-models` used it).

## Implementation

1. Add `DatabaseConnectionMiddleware` to `plain-models`
2. Update `/plain-install` skill to add it to `MIDDLEWARE`
3. Replace signal sends in `plain-jobs/workers.py` with direct function calls
4. Remove signal connects from `plain-models` package config
5. Remove `request_started` / `request_finished` sends from `BaseHandler`
6. Delete `plain/signals.py` and `plain.signals` module
7. Remove test fixtures that disconnect/reconnect signal handlers
