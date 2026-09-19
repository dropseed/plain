"""Raw-path resolver behavior — double slashes, dot segments, encoded sequences.

The resolver normalizes paths per RFC 3986 §5.2.4 before matching:

- Empty segments (from `//`) are dropped; if the input differed from the
  canonical form, the client gets a 308 redirect to it.
- `.` and `..` segments resolve per RFC 3986; `.` is dropped, `..` pops
  the previous segment.
- `..` that would resolve below the URL root returns 400 — there's no
  legitimate request that does that.
- Encoded slashes (`%2F`) are a spec-level limitation: WSGI/ASGI decodes
  them before the framework sees the request, so they look indistinguishable
  from literal `/`. Tests pin the current observed behavior.

These are internal because they pin implementation behavior of the
segment resolver's path-parser layer. The trailing-slash and route
matching contracts live in the public test files.
"""

from __future__ import annotations

from clients import path_client


def test_canonical_path_resolves():
    with path_client() as client:
        response = client.get("/target/")
        assert response.status_code == 200
        assert response.content == b"target GET"


def test_double_slash_in_middle_redirects():
    """`/target//extra` — the resolver collapses `//` and 308-redirects to the
    normalized form. The destination `/target/extra` itself doesn't match a
    route, so following the redirect would 404 — the redirect itself is the
    pinned behavior here.
    """
    with path_client() as client:
        response = client.get("/target//extra")
        assert response.status_code == 308
        assert response.headers["Location"] == "/target/extra"


def test_double_slash_at_root_unreachable_via_client():
    """`//target/` — urlparse strips the leading double-slash to netloc form
    before the request even reaches the framework. The test client therefore
    sends `/` as the path, which doesn't match any PathRouter route → 404.

    Real HTTP clients that send `//target/` raw would hit the framework's
    normalizer and get a 308 to `/target/`; we just can't test that path
    through `Client()` because urlparse intercepts it.
    """
    with path_client() as client:
        response = client.get("//target/")
        assert response.status_code == 404


def test_triple_slash_at_root_unreachable_via_client():
    """`///target/` — urlparse collapses the leading slashes to `/target/`
    before the framework sees it (`urlparse('///target/').path == '/target/'`).
    The resolver then matches the route directly → 200. The framework's own
    normalizer doesn't see the triple slash.
    """
    with path_client() as client:
        response = client.get("///target/")
        assert response.status_code == 200


def test_dot_segment_parent_redirects():
    """`/target/../target/` — `..` pops `target`, then `target/` is added back.
    Canonical form is `/target/`; client gets a 308.
    """
    with path_client() as client:
        response = client.get("/target/../target/")
        assert response.status_code == 308
        assert response.headers["Location"] == "/target/"


def test_dot_segment_current_redirects():
    """`/./target/` — `.` segment is dropped; canonical form is `/target/`;
    client gets a 308.
    """
    with path_client() as client:
        response = client.get("/./target/")
        assert response.status_code == 308
        assert response.headers["Location"] == "/target/"


def test_dot_segment_pops_below_root_is_400():
    """`/target/../..` — `..` pops `target`, then `..` would pop below root.
    The resolver rejects as 400 rather than silently 404'ing.
    """
    with path_client() as client:
        response = client.get("/target/../..")
        assert response.status_code == 400


def test_dot_segment_at_root_is_400():
    """`/..` — single `..` at root. Below-root traversal → 400."""
    with path_client() as client:
        response = client.get("/..")
        assert response.status_code == 400


def test_encoded_slash_double_encoded_by_client():
    """`/target%2F` — the test Client re-encodes `%` → `%25`, so the server sees `%252F`.

    The server decodes once → `%2F` (literal characters in path), which
    doesn't match `target/`. Pinned as a known WSGI/ASGI-level limitation
    the framework can't fully solve.
    """
    with path_client() as client:
        response = client.get("/target%2F")
        assert response.status_code == 404


def test_double_encoded_dots():
    """`/target%252e%252e` — server decodes once to `/target%2e%2e`.

    A literal `%2e%2e` segment doesn't match any route — 404. The
    resolver's dot-segment handling operates on already-decoded `.` and
    `..`, not on their percent-encoded forms.
    """
    with path_client() as client:
        response = client.get("/target%252e%252e")
        assert response.status_code == 404
