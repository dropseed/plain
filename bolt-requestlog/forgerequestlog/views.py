from django.views.generic import TemplateView

from . import settings
from .core import RequestLog


class RequestLogView(TemplateView):
    template_name = "requestlog/requestlog.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        requestlogs = RequestLog.load_json_logs()

        if self.request.GET.get("log"):
            try:
                requestlog = [
                    x for x in requestlogs if x.get("name") == self.request.GET["log"]
                ][0]
            except IndexError:
                requestlog = None
        elif requestlogs:
            requestlog = requestlogs[0]
        else:
            requestlog = None

        ctx["requestlogs"] = requestlogs
        ctx["requestlog"] = requestlog

        if (
            self.request.headers.get("referer")
            and settings.REQUESTLOG_URL() not in self.request.headers["referer"]
        ):
            # TODO keep track of last non-requestlog url in session, use that
            ctx["requestlog_exit_url"] = self.request.headers["referer"]
        else:
            ctx["requestlog_exit_url"] = "/"

        return ctx
