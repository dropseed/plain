"""Pin raw-path resolver behavior — double slashes, dot segments, encoded sequences.

Internal because these tests pin implementation-detail behavior of the
current "regex resolver on un-normalized path" approach. Step #3 of the
URL routing arc replaces that with pre-routing path normalization, and
most of these assertions will flip (404 → 308 or 200).

The route under test is `path("target/", ...)`. The variations probe
what the resolver does when the request path isn't the canonical form.
"""

from __future__ import annotations


def test_canonical_path_resolves(path_client):
    response = path_client.get("/target/")
    assert response.status_code == 200
    assert response.content == b"target GET"


def test_double_slash_in_middle(path_client):
    """`/target//extra` — extra path segment after a double slash → 404.

    Step #3 normalizes `//` → `/` before routing; this becomes a normal
    "extra segment" 404 (no spurious double-slash interpretation).
    """
    response = path_client.get("/target//extra")
    assert response.status_code == 404


def test_double_slash_at_root(path_client):
    """`//target/` — leading double slash → 404 today.

    Step #3: normalizes to `/target/` and 308-redirects.
    """
    response = path_client.get("//target/")
    assert response.status_code == 404


def test_triple_slash_at_root(path_client):
    """`///target/` — triple leading slash is collapsed somewhere upstream.

    Surprising current behavior — the request arrives at the resolver as
    `/target/` and resolves. Pinned so step #3 makes the collapse explicit
    (at the framework's normalization layer rather than upstream).
    """
    response = path_client.get("///target/")
    assert response.status_code == 200


def test_dot_segment_parent(path_client):
    """`/target/../target/` — dot segments → 404 today.

    Step #3 resolves `..` per RFC 3986 before routing; this becomes
    equivalent to `/target/` and resolves.
    """
    response = path_client.get("/target/../target/")
    assert response.status_code == 404


def test_dot_segment_current(path_client):
    """`/./target/` — `.` segment → 404 today.

    Step #3 strips `.` segments; resolves to `/target/`.
    """
    response = path_client.get("/./target/")
    assert response.status_code == 404


def test_encoded_slash_double_encoded_by_client(path_client):
    """`/target%2F` — the test Client re-encodes `%` → `%25`, so the server sees `%252F`.

    The server decodes once → `%2F` (literal characters in path), which
    doesn't match `target/`. Pinned: 404 today. The future doc flags
    encoded slashes as a known spec-level limitation Plain can't fully
    solve, since WSGI/ASGI servers handle this inconsistently.
    """
    response = path_client.get("/target%2F")
    assert response.status_code == 404


def test_double_encoded_dots(path_client):
    """`/target%252e%252e` — server decodes once to `/target%2e%2e`.

    Pinned to whatever happens today. Step #3 documents this as a known
    spec-level limitation rather than fully solving it.
    """
    response = path_client.get("/target%252e%252e")
    assert response.status_code == 404
