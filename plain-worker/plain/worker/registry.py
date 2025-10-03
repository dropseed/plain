from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from .parameters import JobParameters

if TYPE_CHECKING:
    from .jobs import Job

T = TypeVar("T", bound=type["Job"])


class JobsRegistry:
    def __init__(self) -> None:
        self.jobs: dict[str, type[Job]] = {}
        self.ready = False

    def register_job(self, job_class: type[Job], alias: str = "") -> None:
        name = self.get_job_class_name(job_class)
        self.jobs[name] = job_class

        if alias:
            self.jobs[alias] = job_class

    def get_job_class_name(self, job_class: type[Job]) -> str:
        return f"{job_class.__module__}.{job_class.__qualname__}"

    def get_job_class(self, name: str) -> type[Job]:
        return self.jobs[name]

    def load_job(self, job_class_name: str, parameters: dict[str, Any]) -> Job:
        if not self.ready:
            raise RuntimeError("Jobs registry is not ready yet")

        job_class = self.get_job_class(job_class_name)
        args, kwargs = JobParameters.from_json(parameters)
        return job_class(*args, **kwargs)


jobs_registry = JobsRegistry()


def register_job(
    job_class: T | None = None, *, alias: str = ""
) -> T | Callable[[T], T]:
    """
    A decorator that registers a job class in the jobs registry with an optional alias.
    Can be used both with and without parentheses.
    """
    if job_class is None:

        def wrapper(cls: T) -> T:
            jobs_registry.register_job(cls, alias=alias)
            return cls

        return wrapper
    else:
        jobs_registry.register_job(job_class, alias=alias)
        return job_class
