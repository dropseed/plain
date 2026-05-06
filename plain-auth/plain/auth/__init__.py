from importlib.metadata import version

__version__ = version("plain.auth")

from .requests import get_request_user
from .sessions import login, logout

__all__ = [
    "login",
    "logout",
    "get_request_user",
]
