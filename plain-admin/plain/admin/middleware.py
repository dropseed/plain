from plain.http import HttpMiddleware, Request, Response

from .impersonate.middleware import ImpersonateMiddleware


class AdminMiddleware(HttpMiddleware):
    """All admin-related middleware in a single class."""

    def process_request(self, request: Request) -> Response:
        return ImpersonateMiddleware(self.get_response).process_request(request)
