"""Pin `include()` / `path()` slash-boundary normalization.

Internal because these tests cover implementation surface — how route
strings are normalized inside the constructors before becoming regex
patterns. The user-facing `reverse()` round-trips live in the public
test file.

After step #1 of the URL routing arc:
- `include()` strips leading/trailing slashes and forces a single
  trailing slash on non-empty prefixes, so `include("admin")`,
  `include("admin/")`, and `include("/admin/")` all produce the same
  routes.
- `path()` strips leading slashes, so `path("/users/")` is equivalent
  to `path("users/")`. Trailing slashes are still meaningful (decided
  by `urls-trailing-slash-convention`).
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


def test_include_without_trailing_slash_resolves(boundary_client):
    """`include("admin-boundary", ...)` — missing trailing slash is normalized.

    The constructor appends `/`, so `include("admin-boundary")` resolves
    children at `/admin-boundary/...` just like `include("admin-boundary/")`
    would.
    """
    response = boundary_client.get("/admin-boundary/home/")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_include_without_slash_no_longer_concatenates(boundary_client):
    """The old quirk (`/admin-boundaryhome/` resolving) is gone.

    Before step #1 the include prefix `admin-boundary` and child
    `home/` joined without a separator. After normalization the include
    pattern always ends with `/`, so the concatenated form is a 404.
    """
    response = boundary_client.get("/admin-boundaryhome/")
    assert response.status_code == 404


def test_root_include_resolves(boundary_client):
    """`include("", ...)` → child route reachable at its bare path."""
    response = boundary_client.get("/root-hello/")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_include_with_leading_slash_resolves(boundary_client):
    """`include("/admin-leading/", ...)` — leading slash is stripped.

    The constructor normalizes the route to `admin-leading/`, so child
    routes resolve under the expected `/admin-leading/...` prefix.
    """
    response = boundary_client.get("/admin-leading/home/")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_path_with_leading_slash_resolves(boundary_client):
    """`path("/leading-slash/", ...)` — leading slash is stripped.

    `path()` accepts the leading slash form; it's normalized to
    `leading-slash/` before becoming a regex.
    """
    response = boundary_client.get("/leading-slash/")
    assert response.status_code == 200
    assert response.content == b"hello"
