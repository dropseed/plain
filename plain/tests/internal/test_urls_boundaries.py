"""Pin `include()` / `path()` slash-boundary normalization.

Internal because these tests cover implementation surface — how route
strings are normalized inside the constructors before becoming routes.

- `include()` strips leading slashes (no scheme-relative URL hazard) but
  preserves the trailing slash as the canonical-form signal for the
  include's index URL. The separator between prefix and child segments
  is enforced structurally by segment-based matching, not by string
  manipulation, so `/adminhome` collisions are impossible regardless of
  the user's trailing slash choice.
- `path()` strips leading slashes; trailing slash is meaningful.
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
    """`include("admin-boundary", ...)` — no-slash include still resolves
    its slashed children correctly. The child's own slash flag wins (it
    has segments of its own), so `/admin-boundary/home/` matches.
    """
    response = boundary_client.get("/admin-boundary/home/")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_include_without_slash_no_longer_concatenates(boundary_client):
    """The `/adminhome/`-style collision is structurally impossible —
    segments are split on `/` before matching, so the include prefix
    and child's first segment can't merge regardless of slash choice.
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
