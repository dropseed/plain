from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.http import Request, Response


class HttpMiddleware:
    """
    Base class for HTTP middleware using before/after phases.

    Subclasses override before_request() and/or after_response():

        class MyMiddleware(HttpMiddleware):
            def before_request(self, request: Request) -> Response | None:
                # Return Response to short-circuit, or None to continue
                return None

            def after_response(self, request: Request, response: Response) -> Response:
                # Modify and return the response
                return response
    """

    def before_request(self, request: Request) -> Response | None:
        """Return Response to short-circuit, or None to continue."""
        return None

    def after_response(self, request: Request, response: Response) -> Response:
        """Modify and return the response."""
        return response
