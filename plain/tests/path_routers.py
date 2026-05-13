"""URL routes for exercising raw-path edge cases.

A single route is enough — these tests poke at the request path itself
(double slashes, dot segments, encoded sequences) and observe how the
resolver responds. Pinned so step #3 (pre-routing normalization) can
flip the assertions in a visible diff.
"""

from __future__ import annotations

from plain.http import Response
from plain.urls import Router, path
from plain.views import View


class TargetView(View):
    def get(self):
        return Response("target GET")


class PathRouter(Router):
    namespace = ""
    urls = [
        path("target/", TargetView, name="target"),
    ]
