JOBS_RESULTS_RETENTION: int = 60 * 60 * 24 * 7  # One week
JOBS_TIMEOUT: int = 60 * 60 * 24  # One day
JOBS_MIDDLEWARE: list[str] = [
    "plain.jobs.middleware.AppLoggerMiddleware",
]
JOBS_SCHEDULE: list[tuple[str, str]] = []
JOBS_WORKER_MAX_PROCESSES: int | None = None
JOBS_WORKER_MAX_JOBS_PER_PROCESS: int | None = None
JOBS_WORKER_MAX_PENDING_PER_PROCESS: int = 10
JOBS_WORKER_STATS_EVERY: int = 60
