from importlib.metadata import version

__version__ = version("plain.sessions")

from .core import SessionStore
from .exceptions import SessionNotAvailable
from .requests import get_request_session

__all__ = [
    "SessionStore",
    "SessionNotAvailable",
    "get_request_session",
]
