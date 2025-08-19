import re

from plain.http import ResponseRedirect
from plain.runtime import settings


class HttpsRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

        # Settings for https (compile regexes once)
        self.https_redirect_enabled = settings.HTTPS_REDIRECT_ENABLED
        self.https_redirect_host = settings.HTTPS_REDIRECT_HOST
        self.https_redirect_exempt = [
            re.compile(r) for r in settings.HTTPS_REDIRECT_EXEMPT_PATHS
        ]

    def __call__(self, request):
        """
        Rewrite the URL based on settings.APPEND_SLASH
        """

        if redirect_response := self.maybe_https_redirect(request):
            return redirect_response

        return self.get_response(request)

    def maybe_https_redirect(self, request):
        if (
            self.https_redirect_enabled
            and not request.is_https()
            and not any(
                pattern.search(request.path_info)
                for pattern in self.https_redirect_exempt
            )
        ):
            host = self.https_redirect_host or request.get_host()
            return ResponseRedirect(
                f"https://{host}{request.get_full_path()}", status_code=301
            )
