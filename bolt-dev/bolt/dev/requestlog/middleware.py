import sys

from bolt.runtime import settings
from bolt.signals import got_request_exception

from .core import RequestLog


def should_capture_request(request):
    if not settings.DEBUG:
        return False

    if (
        request.resolver_match
        and request.resolver_match.default_namespace == "requestlog"
    ):
        return False

    if request.path in settings.REQUESTLOG_IGNORE_URL_PATHS:
        return False

    # This could be an attribute set on request or response
    # or something more dynamic
    if "querystats" in request.GET:
        return False

    return True


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.exception = None  # If an exception occurs, we want to remember it

        got_request_exception.connect(self.store_exception)

    def __call__(self, request):
        # Process it first, so we know the resolver_match
        response = self.get_response(request)

        if should_capture_request(request):
            RequestLog(
                request=request, response=response, exception=self.exception
            ).save()

        return response

    def store_exception(self, **kwargs):
        """
        The signal calls this at the right time,
        so we can use sys.exxception to capture.
        """
        self.exception = sys.exception()
