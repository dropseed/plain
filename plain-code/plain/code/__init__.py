from importlib.metadata import version

__version__ = version("plain.code")

from .cli import cli

__all__ = ["cli"]
