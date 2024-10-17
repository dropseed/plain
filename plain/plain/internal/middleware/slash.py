from plain.http import ResponsePermanentRedirect
from plain.runtime import settings
from plain.urls import is_valid_path
from plain.utils.http import escape_leading_slashes


class RedirectSlashMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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
            return ResponsePermanentRedirect(self.get_full_path_with_slash(request))

        return response

    def should_redirect_with_slash(self, request):
        """
        Return True if settings.APPEND_SLASH is True and appending a slash to
        the request path turns an invalid path into a valid one.
        """
        if settings.APPEND_SLASH and not request.path_info.endswith("/"):
            urlconf = getattr(request, "urlconf", None)
            if not is_valid_path(request.path_info, urlconf):
                match = is_valid_path("%s/" % request.path_info, urlconf)
                if match:
                    view = match.func
                    return getattr(view, "should_append_slash", True)
        return False

    def get_full_path_with_slash(self, request):
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
                "You called this URL via {method}, but the URL doesn't end "
                "in a slash and you have APPEND_SLASH set. Plain can't "
                "redirect to the slash URL while maintaining {method} data. "
                "Change your form to point to {url} (note the trailing "
                "slash), or set APPEND_SLASH=False in your Plain settings.".format(
                    method=request.method,
                    url=request.get_host() + new_path,
                )
            )
        return new_path
