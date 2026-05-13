from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from plain.http import HttpMiddleware, RedirectResponse
from plain.urls import Resolver404, get_resolver
from plain.utils.encoding import iri_to_uri
from plain.utils.http import escape_leading_slashes

if TYPE_CHECKING:
    from plain.http import Request, Response


class RedirectSlashMiddleware(HttpMiddleware):
    """Bidirectional 308 redirect to the route's canonical trailing-slash form.

    If a request 404s and the opposite trailing-slash form would have matched
    a route, 308-redirect to that form. The route definition is the source of
    truth: `path("users/", ...)` makes `/users` redirect to `/users/`, and
    `path("users", ...)` makes `/users/` redirect to `/users`.

    Status 308 preserves the request method and body, so POST/PUT/PATCH
    survive intact — no more silent body loss like 301 caused.
    """

    def after_response(self, request: Request, response: Response) -> Response:
        if response.status_code != 404:
            return response

        alternate = self._alternate_slash_form(request.path)
        if alternate is None:
            return response
        if not self._path_resolves(alternate):
            return response

        # The view may have chosen to 404 from a route that did match (e.g.
        # an explicit `JsonNotFoundView`). Don't intervene in that case.
        if self._path_resolves(request.path):
            return response

        # Safe-char set matches `Request.get_full_path` (RFC 3986 §3.3, minus
        # ";", "=", "?"). We don't reuse `get_full_path` because it always
        # uses `request.path`, and we need the alternate path here.
        escaped_path = quote(alternate, safe="/:@&+$,-_.!~*'()")
        query = (
            "?" + (iri_to_uri(request.query_string) or "")
            if request.query_string
            else ""
        )
        return RedirectResponse(
            escape_leading_slashes(f"{escaped_path}{query}"),
            status_code=308,
        )

    @staticmethod
    def _alternate_slash_form(path: str) -> str | None:
        if path == "/":
            return None
        if path.endswith("/"):
            return path[:-1]
        return path + "/"

    @staticmethod
    def _path_resolves(path: str) -> bool:
        try:
            get_resolver().resolve(path)
            return True
        except Resolver404:
            return False
