# plain-jobs: Batch Job Pickup

- Fetch multiple jobs at once instead of one-by-one
- Reduces database round trips for high-throughput workloads
- Inspired by Solid Queue's `batch_size` configuration (default 500)

## Current Behavior

Jobs are picked up one at a time in `workers.py`:

```python
job_request = (
    JobRequest.query.select_for_update(skip_locked=True)
    .filter(queue__in=self.queues)
    .filter(models.Q(start_at__isnull=True) | models.Q(start_at__lte=timezone.now()))
    .order_by("priority", "-start_at", "-created_at")
    .first()  # One job at a time
)
```

Each job pickup requires a DB query + transaction.

## Proposed Configuration

Add to `plain/plain/jobs/default_settings.py`:

```python
JOBS_BATCH_SIZE = 1  # Number of jobs to fetch per database query
```

Or CLI flag:

```
--batch-size  # Override JOBS_BATCH_SIZE
```

## Implementation Approach

### Option A: Batch fetch, individual locks

```python
# Fetch batch of job IDs
job_ids = (
    JobRequest.query
    .filter(queue__in=self.queues)
    .filter(models.Q(start_at__isnull=True) | models.Q(start_at__lte=timezone.now()))
    .order_by("priority", "-start_at", "-created_at")
    .values_list("id", flat=True)[:batch_size]
)

# Then lock and process each
for job_id in job_ids:
    job_request = (
        JobRequest.query.select_for_update(skip_locked=True)
        .filter(id=job_id)
        .first()
    )
    if job_request:
        # Process it
```

### Option B: Batch lock (PostgreSQL only)

```python
job_requests = list(
    JobRequest.query.select_for_update(skip_locked=True)
    .filter(queue__in=self.queues)
    .filter(models.Q(start_at__isnull=True) | models.Q(start_at__lte=timezone.now()))
    .order_by("priority", "-start_at", "-created_at")
    [:batch_size]
)
```

This locks multiple rows at once. Works with PostgreSQL's `skip_locked`.

## Trade-offs

**Benefits:**

- Fewer DB queries for high-volume workloads
- Better throughput when workers outnumber available jobs

**Drawbacks:**

- Adds complexity to the pickup loop
- Current approach is simple and works well
- Most apps don't have enough job volume to benefit

## When This Matters

- Apps processing 1000+ jobs/minute
- Multiple workers competing for the same queue
- Database latency is a bottleneck

## Recommendation

Keep default at `batch_size=1` for simplicity. Only expose this configuration if real-world benchmarks show meaningful improvement.
