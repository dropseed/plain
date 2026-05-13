"""Minimal error-raising views for plain core tests.

The template-using error fixtures (and the `{status}.html` rendering
integration tests) live in plain-templates. This module keeps only what
plain core needs: a plain `View` that raises a 500 so OTel exception
recording can be exercised without depending on the templates package.
"""

from __future__ import annotations

from plain.http import NotFoundError404
from plain.urls import Router, path
from plain.views import View


class PlainViewRaises404(View):
    def get(self):
        raise NotFoundError404("plain view says not found")


class PlainViewRaises500(View):
    def get(self):
        raise RuntimeError("plain view boom")


class ErrorRouter(Router):
    namespace = ""
    urls = [
        path("plain-404/", PlainViewRaises404, name="plain-404"),
        path("plain-500/", PlainViewRaises500, name="plain-500"),
    ]
