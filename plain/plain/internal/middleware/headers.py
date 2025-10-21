from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HttpMiddleware
from plain.runtime import settings

if TYPE_CHECKING:
    from plain.http import Request, Response


class DefaultHeadersMiddleware(HttpMiddleware):
    def process_request(self, request: Request) -> Response:
        response = self.get_response(request)

        for header, value in settings.DEFAULT_RESPONSE_HEADERS.items():
            # Since we don't have a good way to *remote* default response headers,
            # use allow users to set them to an empty string to indicate they should be removed.
            if header in response.headers and response.headers[header] == "":
                del response.headers[header]
                continue

            response.headers.setdefault(header, value)

        # Add the Content-Length header to non-streaming responses if not
        # already set.
        if not response.streaming and "Content-Length" not in response.headers:
            response.headers["Content-Length"] = str(len(response.content))

        return response
