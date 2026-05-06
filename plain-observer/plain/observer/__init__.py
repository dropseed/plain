from importlib.metadata import version

__version__ = version("plain.observer")

from .core import Observer, ObserverMode

__all__ = ["Observer", "ObserverMode"]
