from importlib.metadata import version

__version__ = version("plain.auth")

from .requests import get_request_user
from .sessions import login, logout

__all__ = [
    "get_request_user",
    "login",
    "logout",
]
