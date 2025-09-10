from plain.logs import app_logger


class AppLoggerMiddleware:
    def __init__(self, run_job):
        self.run_job = run_job

    def __call__(self, job):
        with app_logger.include_context(
            job_request_uuid=str(job.job_request_uuid), job_uuid=str(job.uuid)
        ):
            return self.run_job(job)
