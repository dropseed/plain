from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HttpMiddleware, ResponseRedirect

if TYPE_CHECKING:
    from plain.http import Request, Response


class RedirectionMiddleware(HttpMiddleware):
    def process_request(self, request: Request) -> Response:
        response = self.get_response(request)

        if response.status_code == 404:
            from .models import NotFoundLog, Redirect, RedirectLog

            redirects = Redirect.query.filter(enabled=True).only(
                "id", "from_pattern", "to_pattern", "http_status", "is_regex"
            )
            for redirect in redirects:
                if redirect.matches_request(request):
                    # Log it
                    redirect_log = RedirectLog.from_redirect(redirect, request)
                    # Then redirect
                    return ResponseRedirect(
                        str(redirect_log.to_url), status_code=redirect.http_status
                    )

            # Nothing matched, just log the 404
            NotFoundLog.from_request(request)

        return response
