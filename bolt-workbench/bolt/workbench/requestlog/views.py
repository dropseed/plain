from bolt.http import HttpResponseRedirect
from bolt.views import TemplateView

from .core import RequestLog


class RequestLogView(TemplateView):
    template_name = "requestlog/requestlog.html"

    def get_context(self):
        ctx = super().get_context()
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

        return ctx

    def post(self):
        if self.request.POST.get("action") == "clear":
            RequestLog.clear()
            return HttpResponseRedirect(self.request.path)
        else:
            RequestLog.replay_request(self.request.POST["log"])
            return HttpResponseRedirect(
                # TODO make this better
                self.request.path
                + "?workbench=requestlog"
            )
