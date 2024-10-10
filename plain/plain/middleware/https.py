import re

from plain.http import ResponsePermanentRedirect
from plain.runtime import settings


class HttpsRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.redirect = settings.HTTPS_REDIRECT_ENABLED
        self.redirect_host = settings.HTTPS_REDIRECT_HOST
        self.redirect_exempt = [re.compile(r) for r in settings.HTTPS_REDIRECT_EXEMPT]

    def __call__(self, request):
        path = request.path.lstrip("/")
        if (
            self.redirect
            and not request.is_secure()
            and not any(pattern.search(path) for pattern in self.redirect_exempt)
        ):
            host = self.redirect_host or request.get_host()
            return ResponsePermanentRedirect(f"https://{host}{request.get_full_path()}")

        return self.get_response(request)
