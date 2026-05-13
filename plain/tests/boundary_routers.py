"""URL routes for exercising `include()` / `path()` slash boundaries.

The interesting cases:
- `include("admin/", ...)` — canonical, works today
- `include("admin", ...)` — works today only because the resolver passes the
  remaining path with no slash adjustment; child patterns that expect a
  trailing slash from the include prefix end up needing a leading slash of
  their own to match. Pinned so step #1 of the URL routing arc makes the
  diff visible.
- `include("", ...)` — root include
- Nested include — `/admin/users/x` through chained includes
"""

from __future__ import annotations

from plain.http import Response
from plain.urls import Router, include, path
from plain.views import View


class HelloView(View):
    def get(self):
        return Response("hello")


class UsersListView(View):
    def get(self):
        return Response("users-list")


class UserDetailView(View):
    def get(self):
        return Response(f"user-{self.url_kwargs['user_id']}")


class NestedRouter(Router):
    namespace = ""
    urls = [
        path("users/", UsersListView, name="users-list"),
        path("users/<int:user_id>/", UserDetailView, name="user-detail"),
    ]


class AdminCanonicalRouter(Router):
    namespace = "admin-canonical"
    urls = [
        path("home/", HelloView, name="home"),
        include("nested/", NestedRouter),
    ]


class AdminBoundaryRouter(Router):
    namespace = "admin-boundary"
    urls = [
        path("home/", HelloView, name="home"),
    ]


class AdminLeadingSlashRouter(Router):
    namespace = "admin-leading"
    urls = [
        path("home/", HelloView, name="home"),
    ]


class RootIncludeRouter(Router):
    namespace = "root-include"
    urls = [
        path("root-hello/", HelloView, name="hello"),
    ]


class BoundaryRouter(Router):
    namespace = ""
    urls = [
        include("admin-canonical/", AdminCanonicalRouter),
        include("admin-boundary", AdminBoundaryRouter),
        include("/admin-leading/", AdminLeadingSlashRouter),
        include("", RootIncludeRouter),
        path("/leading-slash/", HelloView, name="leading-slash"),
    ]
