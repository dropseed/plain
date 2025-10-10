from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from plain.logs import app_logger

if TYPE_CHECKING:
    from .models import JobProcess, JobResult


class AppLoggerMiddleware:
    def __init__(self, run_job: Callable[[JobProcess], JobResult]) -> None:
        self.run_job = run_job

    def __call__(self, job: JobProcess) -> JobResult:
        with app_logger.include_context(
            job_request_uuid=str(job.job_request_uuid), job_process_uuid=str(job.uuid)
        ):
            return self.run_job(job)
