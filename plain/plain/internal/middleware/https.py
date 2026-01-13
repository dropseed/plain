from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HttpMiddleware, RedirectResponse
from plain.runtime import settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request, Response


class HttpsRedirectMiddleware(HttpMiddleware):
    def __init__(self, get_response: Callable[[Request], Response]):
        super().__init__(get_response)

        # Settings for HTTPS
        self.https_redirect_enabled = settings.HTTPS_REDIRECT_ENABLED

    def process_request(self, request: Request) -> Response:
        """
        Perform a blanket HTTP→HTTPS redirect when enabled.
        """

        if redirect_response := self.maybe_https_redirect(request):
            return redirect_response

        return self.get_response(request)

    def maybe_https_redirect(self, request: Request) -> Response | None:
        if self.https_redirect_enabled and not request.is_https():
            return RedirectResponse(
                f"https://{request.host}{request.get_full_path()}", status_code=301
            )
        return None
