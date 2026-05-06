from importlib.metadata import version

__version__ = version("plain.vendor")

from .cli import cli

__all__ = ["cli"]
