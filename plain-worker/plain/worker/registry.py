from plain.models import Model, models_registry


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
        return f"gid://{instance._meta.package_label}/{instance._meta.model_name}/{instance.id}"

    @staticmethod
    def to_instance(s):
        if not s.startswith("gid://"):
            raise ValueError("Invalid ModelInstanceParameter string")
        package, model, obj_id = s[6:].split("/")
        model = models_registry.get_model(package, model)
        return model.objects.get(id=obj_id)

    @staticmethod
    def is_gid(x):
        if not isinstance(x, str):
            return False
        return x.startswith("gid://")


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
