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


class DualSlashView(View):
    def get(self):
        return Response("dual with slash")


class DualNoSlashView(View):
    def get(self):
        return Response("dual without slash")


class ItemView(View):
    def get(self):
        return Response(f"item {self.url_kwargs['id']}")


class SlashRouter(Router):
    namespace = ""
    urls = [
        path("with-slash/", WithSlashView, name="with-slash"),
        path("without-slash", WithoutSlashView, name="without-slash"),
        # Both forms of the same URL are explicitly defined — neither
        # should trigger a redirect; both should resolve to their own view.
        path("dual/", DualSlashView, name="dual-slash"),
        path("dual", DualNoSlashView, name="dual-noslash"),
        # Parameterized slashed route — used to verify the redirect
        # carries converter-matched segments through correctly.
        path("items/<int:id>/", ItemView, name="item-slash"),
    ]
