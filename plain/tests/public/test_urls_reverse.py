"""Contract tests for `reverse()` round-trips.

`reverse()` is contract: views and templates rely on the return value.
These pin current behavior across slash variations and include()
boundaries so subsequent routing changes don't silently shift what URLs
get rendered into HTML.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

from plain.http import Response
from plain.runtime import settings
from plain.test import raises
from plain.urls import Router, get_resolver, include, path, reverse
from plain.urls.exceptions import NoReverseMatch
from plain.urls.resolvers import _get_cached_resolver
from plain.views import View


@contextmanager
def _installed_router(router_path: str):
    original = settings.URLS_ROUTER
    original_ts = settings.URLS_TRAILING_SLASH
    settings.URLS_ROUTER = router_path
    settings.URLS_TRAILING_SLASH = True
    _get_cached_resolver.cache_clear()
    try:
        yield
    finally:
        settings.URLS_ROUTER = original
        settings.URLS_TRAILING_SLASH = original_ts
        _get_cached_resolver.cache_clear()


@contextmanager
def slash_router():
    with _installed_router("slash_routers.SlashRouter"):
        yield


@contextmanager
def boundary_router():
    with _installed_router("boundary_routers.BoundaryRouter"):
        yield


@contextmanager
def use_router(router_class: type[Router]):
    """Install an ad-hoc Router class as `URLS_ROUTER` for a single test.

    Tests that need a one-off router shape (rather than the reusable
    `slash_router`/`boundary_router` shapes) use `with use_router(MyRouter):`
    to install it; the helper restores `URLS_ROUTER` and clears the
    resolver cache on teardown. Stashes the class in the test module's
    globals so `import_string` can resolve it. Sets
    `URLS_TRAILING_SLASH=True` for the duration of the test so slashed
    route strings keep their slash semantics.
    """
    module = sys.modules[__name__]
    attr = "_UseRouterUnderTest"
    module.__dict__[attr] = router_class
    try:
        with _installed_router(f"{__name__}.{attr}"):
            yield
    finally:
        module.__dict__.pop(attr, None)


class _OkView(View):
    def get(self):
        return Response("ok")


def test_reverse_route_with_slash():
    """`path("with-slash/")` → `reverse()` returns `/with-slash/`."""
    with slash_router():
        assert reverse("with-slash") == "/with-slash/"


def test_reverse_route_without_slash():
    """`path("without-slash")` → `reverse()` returns `/without-slash` (no trailing slash)."""
    with slash_router():
        assert reverse("without-slash") == "/without-slash"


def test_reverse_through_canonical_include():
    """`include("admin-canonical/", ...)` + child `path("home/")` → `/admin-canonical/home/`."""
    with boundary_router():
        assert reverse("admin-canonical:home") == "/admin-canonical/home/"


def test_reverse_through_nested_include():
    """Nested include — `/admin-canonical/nested/users/` resolves through chained includes."""
    with boundary_router():
        assert reverse("admin-canonical:users-list") == "/admin-canonical/nested/users/"
        assert (
            reverse("admin-canonical:user-detail", user_id=42)
            == "/admin-canonical/nested/users/42/"
        )


def test_reverse_through_boundary_include_no_slash():
    """`include("admin-boundary", ...)` has no trailing slash on its prefix,
    but the child `path("home/", ...)` has its own slash flag — so the
    rendered URL has a slash because the leaf controls its own canonical
    form. (The include's slash flag matters only for the include's index URL.)
    """
    with boundary_router():
        assert reverse("admin-boundary:home") == "/admin-boundary/home/"


def test_reverse_through_root_include():
    """`include("", ...)` adds no prefix — child route is reachable at its bare path."""
    with boundary_router():
        assert reverse("root-include:hello") == "/root-hello/"


def test_reverse_through_leading_slash_include():
    """`include("/admin-leading/", ...)` — leading slash is stripped.

    `reverse()` produces the same URL as `include("admin-leading/", ...)`.
    """
    with boundary_router():
        assert reverse("admin-leading:home") == "/admin-leading/home/"


def test_reverse_unknown_name_raises():
    with slash_router():
        with raises(NoReverseMatch):
            reverse("not-a-real-name")


def test_reverse_coerces_non_string_value_for_str_converter():
    """Default `str` converter must accept stringifiable values — the old
    `%s` formatting did this implicitly; the new resolver does it via
    `to_url=str`. Regression test for the silent TypeError that bit when
    `to_url` was `_identity`.
    """

    class _Router(Router):
        namespace = ""
        urls = [path("user/<name>/", _OkView, name="user")]

    with use_router(_Router):
        # int gets stringified
        assert reverse("user", name=42) == "/user/42/"


def test_reverse_included_index_follows_global_setting():
    """`path("")` inside `include("admin", AdminRouter)` reverses to
    `/admin/` when `URLS_TRAILING_SLASH=True` (the fixture default).
    The include's slash flag isn't part of the routing model — the
    setting (plus any `force_trailing_slash` on the endpoint) is."""

    class _AdminRouter(Router):
        namespace = "admin"
        urls = [path("", _OkView, name="index")]

    class _Root(Router):
        namespace = ""
        urls = [include("admin", _AdminRouter)]

    with use_router(_Root):
        assert reverse("admin:index") == "/admin/"


def test_reverse_included_index_force_trailing_slash_false():
    """`force_trailing_slash=False` on the included index suppresses the
    slash even under `URLS_TRAILING_SLASH=True`."""

    class _AdminRouter(Router):
        namespace = "admin"
        urls = [path("", _OkView, name="index", force_trailing_slash=False)]

    class _Root(Router):
        namespace = ""
        urls = [include("admin", _AdminRouter)]

    with use_router(_Root):
        assert reverse("admin:index") == "/admin"


def test_reverse_unnamespaced_included_index_follows_global_setting():
    """Same as above but for an un-namespaced include — exercises the
    un-namespaced merge path in `_collect_resolver`."""

    class _AdminRouter(Router):
        namespace = ""
        urls = [path("", _OkView, name="dashboard")]

    class _Root(Router):
        namespace = ""
        urls = [include("admin", _AdminRouter)]

    with use_router(_Root):
        assert reverse("dashboard") == "/admin/"


def test_reverse_suffix_capture_round_trips():
    """`path("form/<slug:slug>.js", ...)` — capture with literal suffix.
    Reverse should interpolate the slug into the segment, and resolve
    should match the rendered URL back. Regression test for the codex
    P1 finding (Pattern segment support).
    """

    class _Router(Router):
        namespace = ""
        urls = [
            path(
                "form/<slug:slug>.js",
                _OkView,
                name="form-js",
                force_trailing_slash=False,
            )
        ]

    with use_router(_Router):
        assert reverse("form-js", slug="contact") == "/form/contact.js"
        match = get_resolver().resolve("/form/contact.js")
        assert match.kwargs == {"slug": "contact"}
        assert match.url_name == "form-js"


def test_reverse_kwarg_can_be_named_prefix_segments():
    """A URL whose capture is named `prefix_segments` must still be
    reversible — the internal `URLResolver.reverse()` parameter of the
    same name is positional-only specifically so this doesn't collide.
    """

    class _Router(Router):
        namespace = ""
        urls = [path("items/<str:prefix_segments>/", _OkView, name="item")]

    with use_router(_Router):
        assert reverse("item", prefix_segments="hello") == "/items/hello/"


def test_reverse_nested_unnamespaced_include_keeps_outer_slash():
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

    with use_router(_Root):
        assert reverse("admin:index") == "/api/"


def test_reverse_does_not_normalize_caller_supplied_values():
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
            # `doc/<path:rest>` is not a catchall (has a literal prefix);
            # opt out of the slash so the test's assertion is stable.
            path(
                "doc/<path:rest>",
                _OkView,
                name="doc",
                force_trailing_slash=False,
            ),
        ]

    with use_router(_Router):
        assert reverse("file", name="..") == "/file/../"
        assert reverse("doc", rest="a//b") == "/doc/a//b"
        assert reverse("doc", rest="a/../b") == "/doc/a/../b"


def test_reverse_escapes_leading_slash_from_path_converter():
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

    with use_router(_Router):
        assert reverse("catch", rest="/evil.com") == "/%2Fevil.com"
        assert reverse("catch", rest="hello/world") == "/hello/world"
