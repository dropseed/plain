from collections.abc import Callable

from plain.http import Request, Response

from .impersonate.middleware import ImpersonateMiddleware


class AdminMiddleware:
    """All admin-related middleware in a single class."""

    def __init__(self, get_response: Callable[[Request], Response]):
        self.get_response = get_response

    def __call__(self, request: Request) -> Response:
        return ImpersonateMiddleware(self.get_response)(request)
