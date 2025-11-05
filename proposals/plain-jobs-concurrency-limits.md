# plain-jobs: Concurrency Limits

Replace binary `unique_key` system with `concurrency_key` + `concurrency_limit` to allow N concurrent jobs instead of just 0 or 1.

## Current System

- `get_unique_key() -> str` returns a key (or empty string for no limit)
- If key is non-empty, only 1 job with that key can be pending/running
- Enforced via database unique constraint + runtime check
- Binary: either unique (1) or unlimited

## Proposed System

- `get_concurrency_key() -> str` for grouping (default: `""`)
- `get_concurrency_limit() -> int | None` for max concurrent (default: `None`)
- Remove database unique constraint
- Pure runtime counting of pending (JobRequest) + running (JobProcess)

## Behavior Examples

- **Empty key + None limit**: Unlimited (no control)
- **Empty key + limit N**: Max N jobs of that job class across all instances
- **Key "foo" + None limit**: Unlimited jobs with key "foo"
- **Key "foo" + limit N**: Max N jobs with key "foo"

## Implementation Points

### Job Class API

```python
def get_concurrency_key(self) -> str:
    """Group jobs for concurrency limiting. Empty string groups by job class."""
    return ""

def get_concurrency_limit(self) -> int | None:
    """Maximum concurrent jobs for this group. None = unlimited."""
    return None
```

### Concurrency Check Logic

Replace `_in_progress()` with `_check_concurrency_limit()`:

- Get limit from `get_concurrency_limit()`, return False if None
- Count matching jobs in JobRequest + JobProcess
- If `concurrency_key` is empty, count by `job_class` only
- If `concurrency_key` is set, count by `(job_class, concurrency_key)`
- Return `total_count >= limit`

### Database Changes

- Rename field: `unique_key` → `concurrency_key`
- Remove unique constraint on JobRequest
- Keep indexes for efficient counting queries
- Migration to rename + drop constraint

### Error Handling

- Remove IntegrityError handling (no unique constraint)
- Change span error from "DuplicateJob" to "ConcurrencyLimitReached"

## Design Decisions

### Why not store concurrency_limit in database?

The limit is a property of the Job class code, not individual instances:

- Never query "show me all jobs with limit=5"
- Historical tracking of limit value isn't useful
- Limits can change between queueing and execution
- Simpler schema

### Retries and concurrency

**Recommended**: Retries should count toward the limit

- Unlike binary unique_key where retries needed bypass (to avoid deadlock)
- With numeric limits, retries can coexist with other jobs
- More predictable behavior
- Pass `concurrency_key` in `retry_job()` to maintain consistency

### Scheduled jobs

- Use special concurrency key: `{job.get_concurrency_key()}:scheduled:{timestamp}`
- With concurrency limits, prevents overlapping scheduled executions
- More explicit than relying on unique constraint

## Use Cases

### Limit by job class

```python
class HeavyProcessingJob(Job):
    def get_concurrency_limit(self):
        return 5  # Max 5 of these jobs system-wide
```

### Limit per user

```python
class ProcessUserDataJob(Job):
    def __init__(self, user_id):
        self.user_id = user_id

    def get_concurrency_key(self):
        return f"user-{self.user_id}"

    def get_concurrency_limit(self):
        return 1  # One job per user at a time
```

### Limit per resource group

```python
class BackupDatabaseJob(Job):
    def __init__(self, database_name):
        self.database_name = database_name

    def get_concurrency_key(self):
        return f"db-{self.database_name}"

    def get_concurrency_limit(self):
        return 2  # Max 2 backups per database
```

## Migration Path

**Breaking changes:**

- Remove `get_unique_key()` entirely
- Rename `unique_key` parameter to `concurrency_key` in `run_in_worker()`
- Database migration required

**Migration guide for users:**

```python
# Before
class MyJob(Job):
    def get_unique_key(self):
        return f"my-job-{self.id}"

# After (equivalent behavior)
class MyJob(Job):
    def get_concurrency_key(self):
        return f"my-job-{self.id}"

    def get_concurrency_limit(self):
        return 1
```

## Trade-offs

**Pros:**

- More flexible than binary unique/unlimited
- No database constraint = simpler error handling
- Clear semantics: "at most N concurrent"
- Easier to reason about for different use cases

**Cons:**

- Breaking change
- No database-level enforcement (race window between check and insert)
- Slightly more complex for simple "unique only" case
- Users need to explicitly set limit=1 for old unique_key behavior

## Open Questions

- Should we provide a helper for the common pattern of "unique per key" (limit=1)?
- Default limit for ScheduledCommand? (probably 1)
- Should limit=0 be valid? (yes - blocks all jobs, useful for maintenance)
