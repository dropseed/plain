from .parameters import JobParameters


class JobsRegistry:
    def __init__(self):
        self.jobs = {}
        self.ready = False

    def register_job(self, job_class, alias=""):
        name = self.get_job_class_name(job_class)
        self.jobs[name] = job_class

        if alias:
            self.jobs[alias] = job_class

    def get_job_class_name(self, job_class):
        return f"{job_class.__module__}.{job_class.__qualname__}"

    def get_job_class(self, name: str):
        return self.jobs[name]

    def load_job(self, job_class_name: str, parameters):
        if not self.ready:
            raise RuntimeError("Jobs registry is not ready yet")

        job_class = self.get_job_class(job_class_name)
        args, kwargs = JobParameters.from_json(parameters)
        return job_class(*args, **kwargs)


jobs_registry = JobsRegistry()


def register_job(job_class=None, *, alias=""):
    """
    A decorator that registers a job class in the jobs registry with an optional alias.
    Can be used both with and without parentheses.
    """
    if job_class is None:

        def wrapper(cls):
            jobs_registry.register_job(cls, alias=alias)
            return cls

        return wrapper
    else:
        jobs_registry.register_job(job_class, alias=alias)
        return job_class
