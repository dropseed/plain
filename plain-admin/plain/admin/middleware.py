from plain.http import HttpMiddleware, Request, Response

from .impersonate.middleware import ImpersonateMiddleware


class AdminMiddleware(HttpMiddleware):
    """All admin-related middleware in a single class."""

    def __init__(self):
        self._impersonate = ImpersonateMiddleware()

    def before_request(self, request: Request) -> Response | None:
        return self._impersonate.before_request(request)
