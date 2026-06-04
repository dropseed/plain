from importlib.metadata import version

__version__ = version("plain.cache")

from .core import Cache, cache

__all__ = [
    "Cache",
    "cache",
]
