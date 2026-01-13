from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HttpMiddleware, RedirectResponse
from plain.runtime import settings
from plain.urls import Resolver404, get_resolver
from plain.utils.http import escape_leading_slashes

if TYPE_CHECKING:
    from plain.http import Request, Response
    from plain.urls import ResolverMatch


class RedirectSlashMiddleware(HttpMiddleware):
    def process_request(self, request: Request) -> Response:
        """
        Rewrite the URL based on settings.APPEND_SLASH
        """

        response = self.get_response(request)

        """
        When the status code of the response is 404, it may redirect to a path
        with an appended slash if should_redirect_with_slash() returns True.
        """
        # If the given URL is "Not Found", then check if we should redirect to
        # a path with a slash appended.
        if response.status_code == 404 and self.should_redirect_with_slash(request):
            return RedirectResponse(
                self.get_full_path_with_slash(request), status_code=301
            )

        return response

    @staticmethod
    def _is_valid_path(path: str) -> ResolverMatch | bool:
        """
        Return the ResolverMatch if the given path resolves against the default URL
        resolver, False otherwise. This is a convenience method to make working
        with "is this a match?" cases easier, avoiding try...except blocks.
        """
        try:
            return get_resolver().resolve(path)
        except Resolver404:
            return False

    def should_redirect_with_slash(self, request: Request) -> ResolverMatch | bool:
        """
        Return True if settings.APPEND_SLASH is True and appending a slash to
        the request path turns an invalid path into a valid one.
        """
        if settings.APPEND_SLASH and not request.path_info.endswith("/"):
            if not self._is_valid_path(request.path_info):
                return self._is_valid_path(f"{request.path_info}/")
        return False

    def get_full_path_with_slash(self, request: Request) -> str:
        """
        Return the full path of the request with a trailing slash appended.

        Raise a RuntimeError if settings.DEBUG is True and request.method is
        POST, PUT, or PATCH.
        """
        new_path = request.get_full_path(force_append_slash=True)
        # Prevent construction of scheme relative urls.
        new_path = escape_leading_slashes(new_path)
        if settings.DEBUG and request.method in ("POST", "PUT", "PATCH"):
            raise RuntimeError(
                f"You called this URL via {request.method}, but the URL doesn't end "
                "in a slash and you have APPEND_SLASH set. Plain can't "
                f"redirect to the slash URL while maintaining {request.method} data. "
                f"Change your form to point to {request.host + new_path} (note the trailing "
                "slash), or set APPEND_SLASH=False in your Plain settings."
            )
        return new_path
