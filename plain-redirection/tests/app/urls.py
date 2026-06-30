"""URL wiring for the plain.redirection test app.

A single index view at ``/`` gives us one real 200 route; every other path
falls through to a 404, which is what triggers the RedirectionMiddleware.
"""

from __future__ import annotations

from plain.http import Response
from plain.urls import Router, path
from plain.views import View


class IndexView(View):
    def get(self) -> Response:
        return Response("Home")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", IndexView, name="index"),
    ]
