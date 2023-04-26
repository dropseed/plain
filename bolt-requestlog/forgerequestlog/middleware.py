from django.conf import settings as django_settings
from django.http import HttpResponseRedirect

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
        if not requestlog_enabled(request):
            return self.get_response(request)

        if request.method == "GET" and request.path == settings.REQUESTLOG_URL():
            return RequestLogView.as_view()(request).render()

        if request.method == "POST" and request.path == settings.REQUESTLOG_URL():
            if request.POST.get("action") == "clear":
                RequestLog.clear()
                return HttpResponseRedirect(request.path)
            else:
                RequestLog.replay_request(request.POST["log"])
                return HttpResponseRedirect(settings.REQUESTLOG_URL())

        response = self.get_response(request)

        RequestLog(request=request, response=response).save()

        return response

    def process_template_response(self, request, response):
        if requestlog_enabled(request):
            response.context_data["requestlog_enabled"] = True
            response.context_data["requestlog_url"] = settings.REQUESTLOG_URL()

        return response
