from importlib.metadata import version

__version__ = version("plain.esbuild")

from .cli import cli

__all__ = ["cli"]
