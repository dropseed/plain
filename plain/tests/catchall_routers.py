from __future__ import annotations

from plain.http import Response
from plain.urls import Router, include, path
from plain.views import View


class _LoginView(View):
    def get(self):
        return Response("login")


class _NotFoundView(View):
    def get(self):
        rest = self.url_kwargs["_"]
        return Response(f"404: {rest}", status_code=404)


class CatchallRouter(Router):
    namespace = ""
    urls = [
        path("login/", _LoginView, name="login"),
        path("<path:_>", _NotFoundView),
    ]


class SlashedCatchallRouter(Router):
    namespace = ""
    urls = [path("<path:_>/", _NotFoundView, name="catchall-slashed")]


class _CatchallOnlyRouter(Router):
    namespace = ""
    urls = [path("<path:_>", _NotFoundView)]


class IncludedCatchallRouter(Router):
    """Catchall lives inside an `include()` — its is_catchall signal must
    propagate up so the outer scope's SlashMismatch still wins.
    """

    namespace = ""
    urls = [
        path("login/", _LoginView, name="login"),
        include("", _CatchallOnlyRouter),
    ]
