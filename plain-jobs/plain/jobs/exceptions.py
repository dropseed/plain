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


class DeferError(Exception):
    """Raised when a deferred job cannot be re-enqueued.

    This typically happens when concurrency limits prevent the job from being
    re-queued. The transaction will be rolled back and the job will remain
    in its current state, then be converted to ERRORED status for retry.
    """

    pass
