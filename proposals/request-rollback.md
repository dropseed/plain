---
packages:
- plain.cli
- plain-models
---

# plain request: Rollback database changes by default

`plain request` is primarily an inspection tool — "show me what this endpoint does." Database changes should be rolled back by default so AI agents (and humans) can safely test any endpoint without side effects.

## Behavior

- **Default**: Wrap the request in a transaction and roll back afterward. Display a message: `Database changes rolled back. Use --commit to persist.`
- **`--commit` flag**: Actually persist database changes (current behavior).
- **Without plain-models**: Silently degrade to current behavior (no transaction wrapping). No database to worry about.

Rollback applies to all HTTP methods, not just non-GET. GET requests can have database side effects too (logging, session creation, counters), so drawing a line between GET and non-GET is a leaky abstraction.

## Caveats

- Only rolls back **database changes**. External side effects (sending emails, calling APIs, writing files) still happen.
- PostgreSQL auto-increment sequences advance even after rollback (cosmetic, usually fine).

## Integration approach

`plain request` lives in core `plain`, but transactions require `plain-models`. Use a try/except import — the same pattern used elsewhere in the codebase (e.g., PIL in `validators.py`):

```python
try:
    from plain.models import transaction
    from plain.models.db import get_connection
    has_models = True
except ImportError:
    has_models = False
```

Then wrap the request:

```python
atomic = None
if has_models and not commit:
    atomic = transaction.atomic()
    atomic._from_testcase = True
    atomic.__enter__()

try:
    # ... existing request logic ...
finally:
    if atomic is not None:
        conn = get_connection()
        conn.set_rollback(True)
        atomic.__exit__(None, None, None)
        conn.close()
        click.secho(
            "Database changes rolled back. Use --commit to persist.",
            fg="cyan",
        )
```

This mirrors the pattern used by the `db` test fixture in `plain-models/plain/models/test/pytest.py`.

## Why not signals?

A signal-based approach (registering handlers in `PackageConfig.ready()`) would be more architecturally "pure" but is overkill. You'd need to pass state (rollback vs commit) through the signal and coordinate an `atomic` context across two separate signal handlers. The try/except import keeps everything in one place.
