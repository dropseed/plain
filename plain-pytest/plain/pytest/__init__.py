from importlib.metadata import version

__version__ = version("plain.pytest")

from .cli import cli

__all__ = ["cli"]
