"""Pin `include()` / `path()` slash-boundary normalization.

Internal because these tests cover implementation surface — how route
strings are normalized inside the constructors before becoming routes.

Both `include()` and `path()` strip leading and trailing slashes from
the route string; slashes carry no per-route signal. The separator
between an include's prefix and its child segments is enforced
structurally by segment-based matching (not by string concatenation),
so `/adminhome` collisions are impossible regardless of how the user
spells the route.

The `boundary_client` fixture installs `URLS_TRAILING_SLASH=True` so
the slashed routes in `boundary_routers.py` keep their canonical
slashed form.
"""

from __future__ import annotations

from clients import boundary_client


def test_canonical_include_resolves():
    """`include("admin-canonical/", ...)` → child route resolves normally."""
    with boundary_client() as client:
        response = client.get("/admin-canonical/home/")
        assert response.status_code == 200
        assert response.content == b"hello"


def test_canonical_include_nested_resolves():
    """Nested `include("nested/", ...)` inside the canonical include resolves."""
    with boundary_client() as client:
        response = client.get("/admin-canonical/nested/users/")
        assert response.status_code == 200
        assert response.content == b"users-list"


def test_canonical_include_nested_with_param():
    """Nested include with URL parameter."""
    with boundary_client() as client:
        response = client.get("/admin-canonical/nested/users/42/")
        assert response.status_code == 200
        assert response.content == b"user-42"


def test_include_without_trailing_slash_resolves():
    """`include("admin-boundary", ...)` — no-slash include still resolves
    its slashed children correctly. Include slash is irrelevant — the
    child route's own slash form (set by `URLS_TRAILING_SLASH=True` in
    this fixture) drives the canonical URL.
    """
    with boundary_client() as client:
        response = client.get("/admin-boundary/home/")
        assert response.status_code == 200
        assert response.content == b"hello"


def test_include_without_slash_no_longer_concatenates():
    """The `/adminhome/`-style collision is structurally impossible —
    segments are split on `/` before matching, so the include prefix
    and child's first segment can't merge regardless of slash choice.
    """
    with boundary_client() as client:
        response = client.get("/admin-boundaryhome/")
        assert response.status_code == 404


def test_root_include_resolves():
    """`include("", ...)` → child route reachable at its bare path."""
    with boundary_client() as client:
        response = client.get("/root-hello/")
        assert response.status_code == 200
        assert response.content == b"hello"


def test_include_with_leading_slash_resolves():
    """`include("/admin-leading/", ...)` — leading slash is stripped.

    The constructor normalizes the route to `admin-leading/`, so child
    routes resolve under the expected `/admin-leading/...` prefix.
    """
    with boundary_client() as client:
        response = client.get("/admin-leading/home/")
        assert response.status_code == 200
        assert response.content == b"hello"


def test_path_with_leading_slash_resolves():
    """`path("/leading-slash/", ...)` — leading slash is stripped.

    `path()` accepts the leading slash form; it's normalized to
    `leading-slash/` before becoming a regex.
    """
    with boundary_client() as client:
        response = client.get("/leading-slash/")
        assert response.status_code == 200
        assert response.content == b"hello"
