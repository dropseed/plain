JOBS_RESULTS_RETENTION: int = 60 * 60 * 24 * 7  # One week
JOBS_HEARTBEAT_INTERVAL: int = 60  # Seconds between worker heartbeat writes
JOBS_HEARTBEAT_TIMEOUT: int = (
    60 * 5
)  # Seconds without a heartbeat before a worker is considered dead and its in-flight jobs marked LOST
JOBS_MIDDLEWARE: list[str] = [
    "plain.jobs.middleware.AppLoggerMiddleware",
]
# Entries are (job, schedule) tuples: a dotted job-class path or "cmd:" string
# (or a Job instance), and a cron string (or a Schedule instance).
JOBS_SCHEDULE: list[tuple] = []
# How far back (in seconds) a missed slot may be and still fire when a
# worker returns — catch-up after ordinary downtime without a stale ledger
# row firing a long-gone slot. Floored at two minutes: anything smaller
# would skip slots that come due between ordinary scheduler passes.
JOBS_SCHEDULE_CATCHUP_WINDOW: int = 60 * 60 * 24
JOBS_WORKER_MAX_PROCESSES: int | None = None
JOBS_WORKER_MAX_JOBS_PER_PROCESS: int | None = None
JOBS_WORKER_MAX_PENDING_PER_PROCESS: int = 10
JOBS_WORKER_STATS_EVERY: int = 60
