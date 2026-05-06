from importlib.metadata import version

__version__ = version("plain.redirection")

from .middleware import RedirectionMiddleware

__all__ = ["RedirectionMiddleware"]
