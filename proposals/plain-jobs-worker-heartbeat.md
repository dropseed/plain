# plain-jobs: Worker Process Heartbeat

- Add periodic heartbeat from worker processes
- Detect stuck/crashed workers faster than current `JOBS_TIMEOUT` (1 day default)
- Inspired by Solid Queue's `process_heartbeat_interval` (60s) and `process_alive_threshold` (5 min)

## Current Behavior

Lost jobs are detected when:

1. A `JobProcess` record exists without a corresponding `JobResult`
2. The job's `created_at` exceeds `JOBS_TIMEOUT` (default 1 day)

This means a crashed worker's jobs won't be retried for up to 24 hours.

## Proposed Design

### New Model: WorkerHeartbeat

```python
class WorkerHeartbeat(models.Model):
    worker_id = models.UUIDField(primary_key=True)
    hostname = models.CharField(max_length=255)
    pid = models.IntegerField()
    queues = models.JSONField()
    last_heartbeat = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["last_heartbeat"]),
        ]
```

### Configuration

Add to `plain/plain/jobs/default_settings.py`:

```python
JOBS_HEARTBEAT_INTERVAL = 60  # Send heartbeat every N seconds
JOBS_HEARTBEAT_TIMEOUT = 300  # Consider worker dead after N seconds without heartbeat
```

### Worker Changes

```python
class Worker:
    def __init__(self, ...):
        self.worker_id = uuid.uuid4()
        self.last_heartbeat = None

    def run(self) -> None:
        self.register_worker()
        try:
            while True:
                self.maybe_send_heartbeat()
                # ... existing job processing
        finally:
            self.deregister_worker()

    def maybe_send_heartbeat(self) -> None:
        now = timezone.now()
        if self.last_heartbeat and (now - self.last_heartbeat).total_seconds() < settings.JOBS_HEARTBEAT_INTERVAL:
            return

        WorkerHeartbeat.objects.update_or_create(
            worker_id=self.worker_id,
            defaults={
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "queues": self.queues,
            }
        )
        self.last_heartbeat = now
```

### Job Rescue Enhancement

Update `rescue_lost_jobs()` to also check for jobs belonging to dead workers:

```python
def rescue_lost_jobs(self) -> None:
    # Existing timeout-based rescue
    # ...

    # New: Rescue jobs from dead workers
    dead_threshold = timezone.now() - timedelta(seconds=settings.JOBS_HEARTBEAT_TIMEOUT)
    dead_workers = WorkerHeartbeat.objects.filter(last_heartbeat__lt=dead_threshold)

    for worker in dead_workers:
        # Find jobs being processed by this worker
        lost_jobs = JobProcess.objects.filter(
            worker_id=worker.worker_id,
            started_at__isnull=False,
        )
        for job in lost_jobs:
            # Mark as lost and potentially retry
            # ...

        worker.delete()
```

## Trade-offs

**Benefits:**

- Detect crashed workers in ~5 minutes instead of 24 hours
- Visibility into active workers via `WorkerHeartbeat` table
- Foundation for worker management UI in admin

**Drawbacks:**

- Extra DB writes (1 per minute per worker)
- New model and migration
- Adds complexity to worker lifecycle

## Alternative: Simpler Approach

Instead of a full heartbeat system, just reduce `JOBS_TIMEOUT` default:

```python
JOBS_TIMEOUT = 3600  # 1 hour instead of 1 day
```

This catches stuck jobs faster without new infrastructure. The downside is it doesn't distinguish between "job is slow" vs "worker crashed".

## Recommendation

Start with reducing `JOBS_TIMEOUT` default. Only implement full heartbeat if users need:

- Sub-minute detection of crashed workers
- Worker management/visibility features
