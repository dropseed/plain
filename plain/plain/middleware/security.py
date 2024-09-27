import re

from plain.http import ResponsePermanentRedirect
from plain.runtime import settings


class SecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.redirect = settings.SECURE_SSL_REDIRECT
        self.redirect_host = settings.SECURE_SSL_HOST
        self.redirect_exempt = [re.compile(r) for r in settings.SECURE_REDIRECT_EXEMPT]

        self.default_headers = settings.SECURE_DEFAULT_HEADERS

    def __call__(self, request):
        path = request.path.lstrip("/")
        if (
            self.redirect
            and not request.is_secure()
            and not any(pattern.search(path) for pattern in self.redirect_exempt)
        ):
            host = self.redirect_host or request.get_host()
            return ResponsePermanentRedirect(f"https://{host}{request.get_full_path()}")

        response = self.get_response(request)

        for header, value in self.default_headers.items():
            response.headers.setdefault(header, value)

        return response
