from importlib.metadata import version

__version__ = version("plain.jobs")

from .exceptions import DeferJob
from .jobs import Job
from .middleware import JobMiddleware
from .registry import register_job

__all__ = ["Job", "DeferJob", "JobMiddleware", "register_job"]
