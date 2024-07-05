from plain import auth
from plain.exceptions import ImproperlyConfigured
from plain.utils.functional import SimpleLazyObject


def get_user(request):
    if not hasattr(request, "_cached_user"):
        request._cached_user = auth.get_user(request)
    return request._cached_user


class AuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not hasattr(request, "session"):
            raise ImproperlyConfigured(
                "The Plain authentication middleware requires session "
                "middleware to be installed. Edit your MIDDLEWARE setting to "
                "insert "
                "'plain.sessions.middleware.SessionMiddleware' before "
                "'plain.auth.middleware.AuthenticationMiddleware'."
            )
        request.user = SimpleLazyObject(lambda: get_user(request))
        response = self.get_response(request)
        return response
