from plain.http import ResponseRedirect
from plain.views import TemplateView

from .requests import RequestLog


class RequestsView(TemplateView):
    template_name = "dev/requests.html"

    def get_template_context(self):
        ctx = super().get_template_context()
        requestlogs = RequestLog.load_json_logs()

        if self.request.query_params.get("log"):
            try:
                requestlog = [
                    x
                    for x in requestlogs
                    if x.get("name") == self.request.query_params["log"]
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
        if self.request.data.get("action") == "clear":
            RequestLog.clear()
            return ResponseRedirect(self.request.path)
        else:
            RequestLog.replay_request(self.request.data["log"])
            return ResponseRedirect(".")
