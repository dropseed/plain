"""Contract tests for `reverse()` round-trips.

`reverse()` is contract: views and templates rely on the return value.
These pin current behavior across slash variations and include()
boundaries so subsequent routing changes don't silently shift what URLs
get rendered into HTML.
"""

from __future__ import annotations

import pytest

from plain.http import Response
from plain.runtime import settings
from plain.urls import Router, get_resolver, include, path, reverse
from plain.urls.exceptions import NoReverseMatch
from plain.urls.resolvers import _get_cached_resolver
from plain.views import View


@pytest.fixture
def slash_router():
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = "slash_routers.SlashRouter"
    _get_cached_resolver.cache_clear()
    try:
        yield
    finally:
        settings.URLS_ROUTER = original
        _get_cached_resolver.cache_clear()


@pytest.fixture
def boundary_router():
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = "boundary_routers.BoundaryRouter"
    _get_cached_resolver.cache_clear()
    try:
        yield
    finally:
        settings.URLS_ROUTER = original
        _get_cached_resolver.cache_clear()


@pytest.fixture
def use_router(request):
    """Install an ad-hoc Router class as `URLS_ROUTER` for a single test.

    Tests that need a one-off router shape (rather than the reusable
    `slash_router`/`boundary_router` shapes) call `use_router(MyRouter)`
    to install it; the fixture restores `URLS_ROUTER` and clears the
    resolver cache on teardown. Stashes the class in the test module's
    globals so `import_string` can resolve it.
    """
    original = settings.URLS_ROUTER
    installed_attr: str | None = None

    def _install(router_class: type[Router]) -> None:
        nonlocal installed_attr
        attr = f"_UseRouter_{request.node.name}"
        request.module.__dict__[attr] = router_class
        installed_attr = attr
        settings.URLS_ROUTER = f"{request.module.__name__}.{attr}"
        _get_cached_resolver.cache_clear()

    try:
        yield _install
    finally:
        settings.URLS_ROUTER = original
        if installed_attr is not None:
            request.module.__dict__.pop(installed_attr, None)
        _get_cached_resolver.cache_clear()


class _OkView(View):
    def get(self):
        return Response("ok")


def test_reverse_route_with_slash(slash_router):
    """`path("with-slash/")` → `reverse()` returns `/with-slash/`."""
    assert reverse("with-slash") == "/with-slash/"


def test_reverse_route_without_slash(slash_router):
    """`path("without-slash")` → `reverse()` returns `/without-slash` (no trailing slash)."""
    assert reverse("without-slash") == "/without-slash"


def test_reverse_through_canonical_include(boundary_router):
    """`include("admin-canonical/", ...)` + child `path("home/")` → `/admin-canonical/home/`."""
    assert reverse("admin-canonical:home") == "/admin-canonical/home/"


def test_reverse_through_nested_include(boundary_router):
    """Nested include — `/admin-canonical/nested/users/` resolves through chained includes."""
    assert reverse("admin-canonical:users-list") == "/admin-canonical/nested/users/"
    assert (
        reverse("admin-canonical:user-detail", user_id=42)
        == "/admin-canonical/nested/users/42/"
    )


def test_reverse_through_boundary_include_no_slash(boundary_router):
    """`include("admin-boundary", ...)` is normalized to `include("admin-boundary/", ...)`.

    Constructors strip leading/trailing slashes and append `/` for
    non-empty prefixes, so this is equivalent to the canonical form.
    """
    assert reverse("admin-boundary:home") == "/admin-boundary/home/"


def test_reverse_through_root_include(boundary_router):
    """`include("", ...)` adds no prefix — child route is reachable at its bare path."""
    assert reverse("root-include:hello") == "/root-hello/"


def test_reverse_through_leading_slash_include(boundary_router):
    """`include("/admin-leading/", ...)` — leading slash is stripped.

    `reverse()` produces the same URL as `include("admin-leading/", ...)`.
    """
    assert reverse("admin-leading:home") == "/admin-leading/home/"


def test_reverse_unknown_name_raises(slash_router):
    with pytest.raises(NoReverseMatch):
        reverse("not-a-real-name")


def test_reverse_coerces_non_string_value_for_str_converter(use_router):
    """Default `str` converter must accept stringifiable values — the old
    `%s` formatting did this implicitly; the new resolver does it via
    `to_url=str`. Regression test for the silent TypeError that bit when
    `to_url` was `_identity`.
    """

    class _Router(Router):
        namespace = ""
        urls = [path("user/<name>/", _OkView, name="user")]

    use_router(_Router)
    # int gets stringified
    assert reverse("user", name=42) == "/user/42/"


def test_reverse_included_index_keeps_trailing_slash(use_router):
    """`path("")` inside `include("admin/", AdminRouter)` is canonically
    served at `/admin/` (the include prefix's trailing slash applies).
    `reverse()` must return `/admin/`, not `/admin` — otherwise links
    would immediately 308 to the canonical form. Regression test for
    the codex P2 finding.
    """

    class _AdminRouter(Router):
        namespace = "admin"
        urls = [path("", _OkView, name="index")]

    class _Root(Router):
        namespace = ""
        urls = [include("admin/", _AdminRouter)]

    use_router(_Root)
    assert reverse("admin:index") == "/admin/"


def test_reverse_unnamespaced_included_index_keeps_trailing_slash(use_router):
    """Same as above but with an un-namespaced include — the prefix flag
    must propagate through `_collect_resolver`'s un-namespaced merge path.
    """

    class _AdminRouter(Router):
        namespace = ""
        urls = [path("", _OkView, name="dashboard")]

    class _Root(Router):
        namespace = ""
        urls = [include("admin/", _AdminRouter)]

    use_router(_Root)
    assert reverse("dashboard") == "/admin/"


def test_reverse_suffix_capture_round_trips(use_router):
    """`path("form/<slug:slug>.js", ...)` — capture with literal suffix.
    Reverse should interpolate the slug into the segment, and resolve
    should match the rendered URL back. Regression test for the codex
    P1 finding (Pattern segment support).
    """

    class _Router(Router):
        namespace = ""
        urls = [path("form/<slug:slug>.js", _OkView, name="form-js")]

    use_router(_Router)
    assert reverse("form-js", slug="contact") == "/form/contact.js"
    match = get_resolver().resolve("/form/contact.js")
    assert match.kwargs == {"slug": "contact"}
    assert match.url_name == "form-js"


def test_reverse_kwarg_can_be_named_prefix_segments(use_router):
    """A URL whose capture is named `prefix_segments` must still be
    reversible — the internal `URLResolver.reverse()` parameter of the
    same name is positional-only specifically so this doesn't collide.
    """

    class _Router(Router):
        namespace = ""
        urls = [path("items/<str:prefix_segments>/", _OkView, name="item")]

    use_router(_Router)
    assert reverse("item", prefix_segments="hello") == "/items/hello/"


def test_reverse_nested_unnamespaced_include_keeps_outer_slash(use_router):
    """`include("api/", ApiRouter(ns=""))` → `include("", AdminRouter(ns="admin"))`
    → `path("")` should give `reverse("admin:index") == "/api/"`.

    The outer include contributes the `/api/` segment + trailing slash;
    the un-namespaced layer adds nothing; the endpoint adds nothing. The
    canonical URL must be `/api/`, not `/api` — otherwise generated links
    immediately 308.
    """

    class _AdminRouter(Router):
        namespace = "admin"
        urls = [path("", _OkView, name="index")]

    class _ApiRouter(Router):
        namespace = ""
        urls = [include("", _AdminRouter)]

    class _Root(Router):
        namespace = ""
        urls = [include("api/", _ApiRouter)]

    use_router(_Root)
    assert reverse("admin:index") == "/api/"


def test_reverse_does_not_normalize_caller_supplied_values(use_router):
    """`reverse()` interpolates kwargs verbatim — it does not validate or
    normalize them. Passing `".."` as a `<str:name>` value or `"a//b"` as
    a `<path:rest>` value produces a URL that 308s elsewhere on resolution,
    breaking round-trip.

    Why: pre-routing normalization (`_parse_path`) is the security boundary.
    `reverse()` trusts internal callers — if you pipe unvalidated user
    input into a URL kwarg, you're responsible for sanitizing it first.
    Adding validation here would be belt-and-suspenders that masks the
    real bug (caller passing untrusted input).

    How to apply: if this assertion ever flips because we added validation
    in `reverse()`, that's a deliberate behavior change — update or remove
    the pin, don't silently work around it.
    """

    class _Router(Router):
        namespace = ""
        urls = [
            path("file/<str:name>/", _OkView, name="file"),
            path("doc/<path:rest>", _OkView, name="doc"),
        ]

    use_router(_Router)
    assert reverse("file", name="..") == "/file/../"
    assert reverse("doc", rest="a//b") == "/doc/a//b"
    assert reverse("doc", rest="a/../b") == "/doc/a/../b"


def test_reverse_escapes_leading_slash_from_path_converter(use_router):
    """When a `<path:...>` capture is the entire URL body and its value
    starts with `/`, the rendered URL would begin with `//` — which
    browsers interpret as a scheme-relative URL (open-redirect hazard).
    `_try_reverse` runs the result through `escape_leading_slashes`, which
    turns the leading `/` of the value into `%2F`.

    Why pin: `<path:...>` accepts arbitrary `/`-containing values per its
    `.+` regex. Internal callers shouldn't be piping untrusted input into
    URL kwargs, but the safety net belongs in the test surface so a future
    rewrite of `_try_reverse` can't silently drop it.
    """

    class _Router(Router):
        namespace = ""
        urls = [path("<path:rest>", _OkView, name="catch")]

    use_router(_Router)
    assert reverse("catch", rest="/evil.com") == "/%2Fevil.com"
    assert reverse("catch", rest="hello/world") == "/hello/world"
