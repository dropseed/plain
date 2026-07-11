from __future__ import annotations


class JobClassNotRegistered(Exception):
    """A job_class name has no registered Job class.

    Usually means the class was renamed or removed in a deploy while
    something still references it — pending database rows (requests,
    retries, results) or a JOBS_SCHEDULE entry.
    """

    def __init__(self, job_class_name: str):
        self.job_class_name = job_class_name
        super().__init__(
            f"Job class '{job_class_name}' is not registered — it may have "
            "been renamed or removed in a deploy."
        )


class DeferJob(Exception):
    """Signal that a job should be deferred and re-tried later.

    Unlike regular exceptions that indicate errors, DeferJob is used for expected
    delays like:
    - Waiting for external resources (API rate limits, data not ready)
    - Polling for status changes
    - Temporary unavailability

    Example:
        # Finite retries - will fail if data never becomes ready
        if not data.is_ready():
            raise DeferJob(delay=60, increment_retries=True)

        # Infinite retries - safe for rate limits
        if rate_limited():
            raise DeferJob(delay=300, increment_retries=False)
    """

    def __init__(self, *, delay: int, increment_retries: bool = False):
        self.delay = delay
        self.increment_retries = increment_retries
        super().__init__(f"Job deferred for {delay} seconds")
