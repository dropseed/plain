from plain.logs import app_logger


class AppLoggerMiddleware:
    def __init__(self, run_job):
        self.run_job = run_job

    def __call__(self, job):
        app_logger.kv.context["job_request_uuid"] = str(job.job_request_uuid)
        app_logger.kv.context["job_uuid"] = str(job.uuid)

        job_result = self.run_job(job)

        app_logger.kv.context.pop("job_request_uuid", None)
        app_logger.kv.context.pop("job_uuid", None)

        return job_result
