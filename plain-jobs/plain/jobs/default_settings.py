JOBS_RESULTS_RETENTION: int = 60 * 60 * 24 * 7  # One week
JOBS_TIMEOUT: int = 60 * 60 * 24  # One day
JOBS_MIDDLEWARE: list[str] = [
    "plain.jobs.middleware.AppLoggerMiddleware",
]
JOBS_SCHEDULE: list[tuple[str, str]] = []
