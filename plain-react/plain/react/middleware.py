from __future__ import annotations

from plain.http import HttpMiddleware, RedirectResponse, Request, Response


class ReactMiddleware(HttpMiddleware):
    """
    Middleware that handles the Plain React SPA navigation protocol.

    Add to your MIDDLEWARE setting:
        MIDDLEWARE = [
            "plain.react.middleware.ReactMiddleware",
            ...
        ]

    Responsibilities:
    - Converts 302 redirects to 303 for PUT/PATCH/DELETE requests
      (prevents browsers from re-submitting with the original method)
    - Passes through validation errors as JSON on react requests
    """

    def process_request(self, request: Request) -> Response:
        response = self.get_response(request)

        if not request.headers.get("X-Plain-React"):
            return response

        # For non-GET React requests that get a 302 redirect,
        # convert to 303 so the browser does a GET to the redirect target.
        # This prevents form resubmission on redirect-after-POST.
        if (
            request.method
            and request.method.upper() in ("PUT", "PATCH", "DELETE", "POST")
            and response.status_code == 302
            and isinstance(response, RedirectResponse)
        ):
            response.status_code = 303

        return response
