from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HttpMiddleware
from plain.runtime import settings

if TYPE_CHECKING:
    from plain.http import Request, Response


class DefaultHeadersMiddleware(HttpMiddleware):
    """
    Applies default response headers from settings.DEFAULT_RESPONSE_HEADERS.

    This middleware runs after the view executes and applies default headers
    to the response using setdefault(), which means:
    - Headers already set by the view won't be overridden
    - Headers not set by the view will use the default value

    View Customization Patterns:
    - Use default: Don't set the header (middleware applies it)
    - Override: Set the header to a different value
    - Remove: Set the header to None (not serialized in the response)
    - Extend: Read from settings.DEFAULT_RESPONSE_HEADERS, modify, then set

    Format Strings:
    Header values can include {request.attribute} placeholders for dynamic
    content. Example: 'nonce-{request.csp_nonce}' will be formatted with
    the request's csp_nonce value. Headers without placeholders are used as-is.
    """

    def process_request(self, request: Request) -> Response:
        # Get the response from the view (and any inner middleware)
        response = self.get_response(request)

        # Apply default headers to the response
        for header, value in settings.DEFAULT_RESPONSE_HEADERS.items():
            if header not in response.headers:
                # Header not set - apply default
                if "{" in value:
                    response.headers[header] = value.format(request=request)
                else:
                    response.headers[header] = value

        # Add the Content-Length header to non-streaming responses if not
        # already set.
        if not response.streaming and "Content-Length" not in response.headers:
            response.headers["Content-Length"] = str(len(response.content))

        return response
