"""Minimal URL routes for exercising trailing-slash behavior.

The fixture sets `URLS_TRAILING_SLASH=True`; routes that want to keep
the no-slash form (regardless of the global setting) declare it with
`force_trailing_slash=False`.
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


class NoteView(View):
    def get(self):
        return Response(f"note {self.url_kwargs['title']}")


class DocsView(View):
    def get(self):
        return Response(f"docs {self.url_kwargs['rest']}")


class SlashRouter(Router):
    namespace = ""
    urls = [
        path("with-slash", WithSlashView, name="with-slash"),
        path(
            "without-slash",
            WithoutSlashView,
            name="without-slash",
            force_trailing_slash=False,
        ),
        # Both forms of the same URL are explicitly defined — neither
        # should trigger a redirect; both should resolve to their own view.
        path("dual", DualSlashView, name="dual-slash"),
        path(
            "dual",
            DualNoSlashView,
            name="dual-noslash",
            force_trailing_slash=False,
        ),
        # Parameterized slashed route — used to verify the redirect
        # carries converter-matched segments through correctly.
        path("items/<int:id>", ItemView, name="item-slash"),
        # String capture — used to verify the canonical-redirect Location
        # header percent-encodes captured values that contain reserved chars.
        path("notes/<str:title>", NoteView, name="note-slash"),
        # Multi-segment `<path:...>` capture — used to verify the route's
        # trailing-slash flag drives the canonical form (the capture itself
        # doesn't swallow the slash).
        path(
            "docs/<path:rest>",
            DocsView,
            name="docs-noslash",
            force_trailing_slash=False,
        ),
    ]
