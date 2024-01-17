import datetime
import inspect
from importlib import import_module

from bolt.db.models import Model


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
                serialized_args.append(ModelInstanceParameter.from_instance(arg))
            else:
                serialized_args.append(arg)

        serialized_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, Model):
                serialized_kwargs[key] = ModelInstanceParameter.from_instance(value)
            else:
                serialized_kwargs[key] = value

        return {"args": serialized_args, "kwargs": serialized_kwargs}

    @staticmethod
    def from_json(data):
        args = []
        for arg in data["args"]:
            if ModelInstanceParameter.is_gid(arg):
                args.append(ModelInstanceParameter.to_instance(arg))
            else:
                args.append(arg)

        kwargs = {}
        for key, value in data["kwargs"].items():
            if ModelInstanceParameter.is_gid(value):
                kwargs[key] = ModelInstanceParameter.to_instance(value)
            else:
                kwargs[key] = value

        return args, kwargs


class ModelInstanceParameter:
    """
    A string representation of a model instance,
    so we can convert a single parameter (model instance itself)
    into a string that can be serialized and stored in the database.
    """

    @staticmethod
    def from_instance(instance):
        return f"gid://{instance._meta.package_label}/{instance._meta.model_name}/{instance.pk}"

    @staticmethod
    def to_instance(s):
        if not s.startswith("gid://"):
            raise ValueError("Invalid ModelInstanceParameter string")
        package, model, pk = s[6:].split("/")
        from bolt.packages import packages

        model = packages.get_model(package, model)
        return model.objects.get(pk=pk)

    @staticmethod
    def is_gid(x):
        if not isinstance(x, str):
            return False
        return x.startswith("gid://")


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
    def run(self):
        raise NotImplementedError

    def run_in_background(self, start_at: datetime.datetime | None = None):
        from .models import JobRequest

        if unique_existing := self._get_existing_unique_job_or_request():
            return unique_existing

        try:
            # Try to automatically annotate the source of the job
            caller = inspect.stack()[1]
            source = f"{caller.filename}:{caller.lineno}"
        except (IndexError, AttributeError):
            source = ""

        parameters = JobParameters.to_json(self._init_args, self._init_kwargs)

        return JobRequest.objects.create(
            job_class=self._job_class_str(),
            parameters=parameters,
            priority=self.get_priority(),
            source=source,
            retries=self.get_retries(),
            start_at=start_at,
        )

    def _job_class_str(self):
        return f"{self.__module__}.{self.__class__.__name__}"

    def _get_existing_unique_job_or_request(self):
        """
        Find pending or running versions of this job that already exist.
        Note this doesn't include instances that may have failed and are
        not yet queued for retry.
        """
        from .models import Job, JobRequest

        job_class = self._job_class_str()
        unique_key = self.get_unique_key()

        if not unique_key:
            return None

        try:
            return JobRequest.objects.get(
                job_class=job_class,
                unique_key=unique_key,
            )
        except JobRequest.DoesNotExist:
            pass

        try:
            return Job.objects.get(
                job_class=job_class,
                unique_key=unique_key,
            )
        except Job.DoesNotExist:
            pass

        return None

    def get_unique_key(self) -> str:
        """
        A unique key to prevent duplicate jobs from being queued.
        Enabled by returning a non-empty string.
        """
        raise ""

    def get_priority(self) -> int:
        return 0

    def get_retries(self) -> int:
        return 0

    def get_retry_delay(self, attempt: int) -> int:
        return 0
