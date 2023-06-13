from django.conf import settings as django_settings


from . import settings
from .core import RequestLog
from .views import RequestLogView


def requestlog_enabled(request):
    return (
        django_settings.DEBUG
        and request.path not in settings.REQUESTLOG_IGNORE_URL_PATHS()
        and "querystats" not in request.GET
    )


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Exit early if not enabled
        if not requestlog_enabled(request):
            return self.get_response(request)

        if request.GET.get("workbench") == "requestlog" or request.POST.get(
            "workbench"
            ) == "requestlog":
            return RequestLogView.as_view()(request).render()

        # Save the request to the log
        response = self.get_response(request)
        RequestLog(request=request, response=response).save()
        return response

    def process_template_response(self, request, response):
        if requestlog_enabled(request):
            response.context_data["requestlog_enabled"] = True

        return response
