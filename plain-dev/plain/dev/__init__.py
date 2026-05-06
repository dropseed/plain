from importlib.metadata import version

__version__ = version("plain.dev")

from .cli import cli

__all__ = ["cli"]
