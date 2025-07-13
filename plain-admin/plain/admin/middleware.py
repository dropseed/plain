from .impersonate.middleware import ImpersonateMiddleware


class AdminMiddleware:
    """All admin-related middleware in a single class."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return ImpersonateMiddleware(self.get_response)(request)
