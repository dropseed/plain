from importlib.metadata import version

__version__ = version("plain.tunnel")

from .cli import cli

__all__ = ["cli"]
