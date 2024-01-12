import datetime
import inspect
from importlib import import_module

from bolt.db.models import Model

from .gid import GlobalID


def load_job(job_class_path, parameters):
    module_path, class_name = job_class_path.rsplit(".", 1)
    module = import_module(module_path)
    job_class = getattr(module, class_name)
    args, kwargs = JobParameters.from_json(parameters)
    return job_class(*args, **kwargs)


class JobParameters:
    @staticmethod
    def to_json(args, kwargs):
        serialized_args = []
        for arg in args:
            if isinstance(arg, Model):
                serialized_args.append(GlobalID.from_instance(arg))
            else:
                serialized_args.append(arg)

        serialized_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, Model):
                serialized_kwargs[key] = GlobalID.from_instance(value)
            else:
                serialized_kwargs[key] = value

        return {"args": serialized_args, "kwargs": serialized_kwargs}

    @staticmethod
    def from_json(data):
        args = []
        for arg in data["args"]:
            if GlobalID.is_gid(arg):
                args.append(GlobalID.to_instance(arg))
            else:
                args.append(arg)

        kwargs = {}
        for key, value in data["kwargs"].items():
            if GlobalID.is_gid(value):
                kwargs[key] = GlobalID.to_instance(value)
            else:
                kwargs[key] = value

        return args, kwargs


class JobType(type):
    """
    Metaclass allows us to capture the original args/kwargs
    used to instantiate the job, so we can store them in the database
    when we schedule the job.
    """

    def __call__(self, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        instance._init_args = args
        instance._init_kwargs = kwargs
        return instance


class Job(metaclass=JobType):
    def run_in_background(self, start_at: datetime.datetime | None = None):
        try:
            # Try to automatically annotate the source of the job
            caller = inspect.stack()[1]
            source = f"{caller.filename}:{caller.lineno}"
        except (IndexError, AttributeError):
            source = ""

        parameters = JobParameters.to_json(self._init_args, self._init_kwargs)

        from .models import JobRequest

        priority = self.get_priority()
        retries = self.get_retries()

        return JobRequest.objects.create(
            job_class=f"{self.__module__}.{self.__class__.__name__}",
            parameters=parameters,
            priority=priority,
            source=source,
            retries=retries,
            start_at=start_at,
        )

    def run(self):
        raise NotImplementedError

    def get_priority(self) -> int:
        return 0

    def get_retries(self) -> int:
        return 0

    def get_retry_delay(self, attempt: int) -> int:
        return 0
