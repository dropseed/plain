WORKER_JOBS_CLEARABLE_AFTER: int = 60 * 60 * 24 * 7  # One week
WORKER_JOBS_LOST_AFTER: int = 60 * 60 * 24  # One day
WORKER_MIDDLEWARE: list[str] = [
    "plain.worker.middleware.AppLoggerMiddleware",
]
WORKER_JOBS_SCHEDULE: list[tuple[str, str]] = []
