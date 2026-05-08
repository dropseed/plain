import time

from plain.jobs import Job, register_job
from plain.logs import app_logger


@register_job
class ExampleJob(Job):
    def run(self) -> None:
        app_logger.info("Example job running", context={"job": "ExampleJob"})
        time.sleep(1)
        app_logger.info("Example job finished", context={"job": "ExampleJob"})
