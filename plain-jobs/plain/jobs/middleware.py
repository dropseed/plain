from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from plain.logs import app_logger

if TYPE_CHECKING:
    from .models import JobProcess, JobResult


class JobMiddleware(ABC):
    """
    Abstract base class for job middleware.

    Subclasses must implement process_job() to handle the job execution cycle.

    Example:
        class MyJobMiddleware(JobMiddleware):
            def process_job(self, job: JobProcess) -> JobResult:
                # Pre-processing
                result = self.run_job(job)
                # Post-processing
                return result
    """

    def __init__(self, run_job: Callable[[JobProcess], JobResult]):
        self.run_job = run_job

    @abstractmethod
    def process_job(self, job: JobProcess) -> JobResult:
        """Process the job and return a result. Must be implemented by subclasses."""
        ...


class AppLoggerMiddleware(JobMiddleware):
    def process_job(self, job: JobProcess) -> JobResult:
        with app_logger.include_context(
            job_request_uuid=str(job.job_request_uuid), job_process_uuid=str(job.uuid)
        ):
            return self.run_job(job)
