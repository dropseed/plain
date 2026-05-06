from importlib.metadata import version

__version__ = version("plain.admin")

from .middleware import AdminMiddleware

__all__ = [
    "AdminMiddleware",
]
