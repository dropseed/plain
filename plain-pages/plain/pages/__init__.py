from importlib.metadata import version

__version__ = version("plain.pages")

from .views import PageView

__all__ = [
    "PageView",
]
