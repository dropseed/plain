from plain.http import Response
from plain.sessions.views import SessionView
from plain.urls import Router, path


class IndexView(SessionView):
    def get(self):
        # Store something so the session is saved
        self.session["foo"] = "bar"
        return Response("test")


class SetView(SessionView):
    def get(self):
        self.session["value"] = self.request.query_params.get("value", "bar")
        return Response("set")


class GetView(SessionView):
    def get(self):
        return Response(self.session.get("value", "<none>"))


class FlushView(SessionView):
    def post(self):
        self.session.flush()
        return Response("flushed")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", IndexView),
        path("set", SetView),
        path("get", GetView),
        path("flush", FlushView),
    ]
