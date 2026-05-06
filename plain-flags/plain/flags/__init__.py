from importlib.metadata import version

__version__ = version("plain.flags")

from .flags import Flag

__all__ = ["Flag"]
