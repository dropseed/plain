"""Minimal URL routes for exercising trailing-slash behavior.

Used by the `slash_client` fixture in conftest.py. The point of these
tests is to pin current behavior so the trailing-slash convention
future can flip the assertions in a legible diff.
"""

from __future__ import annotations

from plain.http import Response
from plain.urls import Router, path
from plain.views import View


class WithSlashView(View):
    def get(self):
        return Response("with-slash GET")

    def post(self):
        return Response("with-slash POST")


class WithoutSlashView(View):
    def get(self):
        return Response("without-slash GET")

    def post(self):
        return Response("without-slash POST")


class SlashRouter(Router):
    namespace = ""
    urls = [
        path("with-slash/", WithSlashView, name="with-slash"),
        path("without-slash", WithoutSlashView, name="without-slash"),
    ]
