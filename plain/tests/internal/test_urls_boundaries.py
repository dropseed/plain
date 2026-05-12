"""Pin current `include()` / `path()` slash-boundary behavior.

Internal because these are change-detector tests — the assertions pin
implementation quirks that step #1 of the URL routing arc is designed to
fix. Won't survive the rewrite; that's the point.

Quirks pinned:
- `include("admin-boundary")` (no trailing slash) is **broken**: GET requests
  to `/admin-boundary/home/` don't resolve because the resolver passes
  `/home/` to the child (with leading slash), and the child pattern expects
  `home/` (no leading slash).
- `path("/leading-slash/", ...)` works at request time (the leading slash
  is incorporated into the regex), but fires a preflight warning.
"""

from __future__ import annotations


def test_canonical_include_resolves(boundary_client):
    """`include("admin-canonical/", ...)` → child route resolves normally."""
    response = boundary_client.get("/admin-canonical/home/")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_canonical_include_nested_resolves(boundary_client):
    """Nested `include("nested/", ...)` inside the canonical include resolves."""
    response = boundary_client.get("/admin-canonical/nested/users/")
    assert response.status_code == 200
    assert response.content == b"users-list"


def test_canonical_include_nested_with_param(boundary_client):
    """Nested include with URL parameter."""
    response = boundary_client.get("/admin-canonical/nested/users/42/")
    assert response.status_code == 200
    assert response.content == b"user-42"


def test_boundary_include_without_slash_is_silently_broken(boundary_client):
    """`include("admin-boundary", ...)` — no trailing slash → child routes don't resolve.

    Step #1 normalizes this to `include("admin-boundary/", ...)` and the
    assertion flips to 200. Today: 404.
    """
    response = boundary_client.get("/admin-boundary/home/")
    assert response.status_code == 404


def test_boundary_include_concatenates_path(boundary_client):
    """`include("admin-boundary")` + child `path("home/")` resolves at `/admin-boundaryhome/`.

    Demonstrates the silent corruption — there's no boundary between the
    include prefix and the child route. Step #1 makes this resolve at the
    expected `/admin-boundary/home/` instead.
    """
    response = boundary_client.get("/admin-boundaryhome/")
    assert response.status_code == 200


def test_root_include_resolves(boundary_client):
    """`include("", ...)` → child route reachable at its bare path."""
    response = boundary_client.get("/root-hello/")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_leading_slash_on_include_does_not_resolve(boundary_client):
    """`include("/admin-leading/", ...)` — leading slash on the include argument.

    Symmetric to `path("/leading-slash/", ...)`: the root resolver strips one
    slash before matching children, so the include's pattern `^/admin-leading/`
    sees `admin-leading/` (no leading slash) and 404s. Step #1 strips leading
    slashes from include() arguments, after which this resolves.
    """
    response = boundary_client.get("/admin-leading/home/")
    assert response.status_code == 404


def test_leading_slash_in_path_route_does_not_resolve(boundary_client):
    """`path("/leading-slash/", ...)` (leading slash in route) → does not resolve today.

    The root resolver strips one leading slash before matching children, so
    the child sees `leading-slash/` while the route pattern is `^/leading-slash/`
    — no match → 404. Step #1 normalizes leading slashes off route strings;
    after that, this resolves at `/leading-slash/`.
    """
    response = boundary_client.get("/leading-slash/")
    assert response.status_code == 404
