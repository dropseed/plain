from plain.sessions.views import SessionViewMixin
from plain.urls import Router, path
from plain.views import View


class IndexView(SessionViewMixin, View):
    def get(self):
        # Store something so the session is saved
        self.session["foo"] = "bar"
        return "test"


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", IndexView),
    ]
