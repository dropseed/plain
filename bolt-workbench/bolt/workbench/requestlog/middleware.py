from bolt.runtime import settings as bolt_settings

from . import settings
from .core import RequestLog


def should_capture_request(request):
    if not bolt_settings.DEBUG:
        return False

    if (
        request.resolver_match
        and request.resolver_match.default_namespace == "requestlog"
    ):
        return False

    if request.path in settings.REQUESTLOG_IGNORE_URL_PATHS():
        return False

    # This could be an attribute set on request or response
    # or something more dynamic
    if "querystats" in request.GET:
        return False

    return True


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process it first, so we know the resolver_match
        response = self.get_response(request)

        if should_capture_request(request):
            RequestLog(request=request, response=response).save()

        return response
