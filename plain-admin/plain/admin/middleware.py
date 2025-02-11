from .impersonate.middleware import ImpersonateMiddleware
from .querystats.middleware import QueryStatsMiddleware


class AdminMiddleware:
    """All admin-related middleware in a single class."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return QueryStatsMiddleware(ImpersonateMiddleware(self.get_response))(request)
