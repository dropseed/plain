# plain-jobs: Configurable Worker Intervals

- Make hardcoded timing intervals configurable via settings and CLI flags
- Inspired by Rails Solid Queue's configurability
- Allows tuning for different workloads (high-volume vs low-volume)

## Current Hardcoded Intervals

| Interval                 | Current Value | Location         |
| ------------------------ | ------------- | ---------------- |
| Job pickup sleep (idle)  | 1 second      | `workers.py:146` |
| Pending queue full sleep | 0.5 seconds   | `workers.py:128` |
| Job rescue check         | 60 seconds    | `workers.py:190` |
| Scheduled jobs check     | 60 seconds    | `workers.py:202` |

## Proposed Configuration

### Settings (with sensible defaults)

Add to `plain/plain/jobs/default_settings.py`:

```python
JOBS_POLLING_INTERVAL = 1.0  # Seconds to sleep when no jobs available
JOBS_MAINTENANCE_INTERVAL = 60  # Seconds between rescue/scheduled job checks
```

### CLI Flags

Add to worker command:

```
--polling-interval  # Override JOBS_POLLING_INTERVAL
```

Environment variable: `PLAIN_JOBS_WORKER_POLLING_INTERVAL`

## Implementation

### 1. Update default_settings.py

```python
JOBS_POLLING_INTERVAL = 1.0  # How often to poll when idle (seconds)
JOBS_MAINTENANCE_INTERVAL = 60  # How often to run maintenance tasks (seconds)
```

### 2. Update cli.py

```python
@click.option(
    "--polling-interval",
    type=float,
    envvar="PLAIN_JOBS_WORKER_POLLING_INTERVAL",
    help="Seconds to sleep when no jobs available (default: from settings)",
)
```

### 3. Update Worker class

```python
def __init__(
    self,
    queues: list[str],
    max_processes: int | None = None,
    max_jobs_per_process: int | None = None,
    max_pending_per_process: int = 10,
    stats_every: int = 60,
    polling_interval: float | None = None,
) -> None:
    self.polling_interval = polling_interval or settings.JOBS_POLLING_INTERVAL
    self.maintenance_interval = settings.JOBS_MAINTENANCE_INTERVAL
    # ...
```

Then use `self.polling_interval` instead of hardcoded `1` in the run loop.

## Use Cases

**High-volume apps**: Lower polling interval (0.1-0.5s) for faster job pickup at cost of more DB queries

**Low-volume apps**: Higher polling interval (5-10s) to reduce DB load when jobs are infrequent

**Development**: Default 1s is fine for most cases

## Not Included (Yet)

These Solid Queue features were considered but deferred:

- **Batch job pickup**: Fetching multiple jobs at once. Current `select_for_update(skip_locked=True)` approach is simple and works well with PostgreSQL.

- **Process heartbeat**: Solid Queue has 60s heartbeat + 5 min alive threshold. Plain-jobs uses `JOBS_TIMEOUT` (1 day default). Could add later if faster stuck-job detection is needed.

- **Concurrency maintenance**: Periodic check for blocked jobs that can be unblocked. Plain-jobs concurrency model is simpler and doesn't need this.

## Notes

- Keep maintenance interval as setting-only (not CLI flag) since it's less commonly tuned
- Polling interval is most useful to expose via CLI for quick testing
- Could add `--fast` convenience flag that sets polling to 0.1s for development
