from plain.sessions.views import SessionView
from plain.urls import Router, path


class IndexView(SessionView):
    def get(self):
        # Store something so the session is saved
        self.session["foo"] = "bar"
        return "test"


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", IndexView),
    ]
