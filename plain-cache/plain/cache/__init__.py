from importlib.metadata import version

__version__ = version("plain.cache")

from .core import Cached

__all__ = [
    "Cached",
]
