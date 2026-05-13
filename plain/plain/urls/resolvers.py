"""
This module converts requested URLs to callback view functions.

URLResolver is the main class here. Its resolve() method takes a URL (as
a string), parses it into segments, and returns a ResolverMatch object
which provides access to all attributes of the resolved URL match.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from plain.exceptions import ImproperlyConfigured
from plain.preflight import PreflightResult
from plain.runtime import settings
from plain.utils.http import RFC3986_SUBDELIMS, escape_leading_slashes
from plain.utils.module_loading import import_string

from .exceptions import NoReverseMatch, Resolver308, Resolver400, Resolver404
from .matches import ResolverMatch
from .paths import BadPath, ParsedPath, RedirectToCanonical, SlashMismatch, _parse_path
from .patterns import URLPattern
from .segments import (
    Capture,
    Literal,
    Route,
    Segment,
    _captures_in,
    _effective_trailing_slash,
    _route_to_segments,
    _segment_value_matches,
    _walk_segments,
)

if TYPE_CHECKING:
    from .routers import Router


# Reverse-lookup entries map a key (view class or name string) to a list
# of candidate segment chains + their trailing-slash flag.
_ReverseEntry = tuple[tuple[Segment, ...], bool]
_ReverseLookups = dict[type | str, list[_ReverseEntry]]
# Namespace entries map a namespace string to its prefix segments,
# prefix trailing-slash flag, and the resolver that owns it.
_NamespaceEntry = tuple[tuple[Segment, ...], bool, "URLResolver"]
_NamespaceLookups = dict[str, _NamespaceEntry]


def get_resolver(router: str | Router | None = None) -> URLResolver:
    if router is None:
        router = settings.URLS_ROUTER

    return _get_cached_resolver(router)


@functools.cache
def _get_cached_resolver(router: str | Router) -> URLResolver:
    if isinstance(router, str):
        router_class = import_string(router)
        router = router_class()

    return URLResolver(route=_route_to_segments(""), raw_route="", router=router)


class URLResolver:
    """A prefix-matcher: matches a `Route` prefix against incoming segments,
    then dispatches to its children (URLPatterns or nested URLResolvers).
    """

    def __init__(
        self,
        *,
        route: Route,
        raw_route: str,
        router: Router,
    ):
        self.route = route
        self.raw_route = raw_route
        self.router = router
        self.namespace = router.namespace
        self.url_patterns = router.urls

        # Eager merge: each child URLResolver already built its own dicts
        # during its own __init__. The URL graph is a DAG constructed
        # bottom-up at include() time, so a child never references its
        # parent — no recursion, no cycle handling needed.
        self.reverse_dict, self.namespace_dict = _build_lookups(self.url_patterns)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} {repr(self.router)} "
            f"({self.namespace}) '{self.raw_route}'>"
        )

    def preflight(self) -> list[PreflightResult]:
        messages: list[PreflightResult] = []
        for pattern in self.url_patterns:
            messages.extend(pattern.preflight())
        return messages

    def resolve(self, path: str) -> ResolverMatch:
        """Entry point for resolving a request URL.

        Parses `path`, raises `Resolver400`/`Resolver308` for malformed or
        non-canonical paths, then walks the route tree. Raises
        `Resolver404` if no route matches.
        """
        path = str(path)  # path may be a reverse_lazy object
        parsed = _parse_path(path)
        if isinstance(parsed, BadPath):
            raise Resolver400(parsed.reason)
        if isinstance(parsed, RedirectToCanonical):
            raise Resolver308(parsed.canonical)
        assert isinstance(parsed, ParsedPath)

        result = self._resolve_segments(
            parsed.segments,
            parsed.trailing_slash,
            prefix_segments=(),
            prefix_kwargs={},
        )
        if isinstance(result, ResolverMatch):
            return result
        if isinstance(result, SlashMismatch):
            # Toggle the slash on the *original* request path — don't rebuild
            # from rendered kwargs, which would normalize opaque captured
            # values (e.g. `<int:id>` rendering `001` → `1`).
            toggled = path[:-1] if path.endswith("/") else path + "/"
            raise Resolver308(toggled)
        raise Resolver404({"path": path})

    def _resolve_segments(
        self,
        segments: tuple[str, ...],
        trailing_slash: bool,
        prefix_segments: tuple[Segment, ...],
        prefix_kwargs: dict[str, Any],
    ) -> ResolverMatch | SlashMismatch | None:
        """Match this resolver's prefix, then walk children.

        Returns:
            ResolverMatch — a child returned an exact match
            SlashMismatch — no exact match, but a child reported a
                trailing-slash mismatch (sibling priority preserved)
            None — neither this resolver's prefix nor any child matched
        """
        match = _walk_segments(self.route.segments, segments, full_match=False)
        if match is None:
            return None
        consumed, captured = match
        kwargs = {**prefix_kwargs, **captured} if captured else prefix_kwargs
        remaining_segments = segments[consumed:]
        merged_prefix = prefix_segments + self.route.segments

        def _wrap(rm: ResolverMatch) -> ResolverMatch:
            return ResolverMatch(
                view_class=rm.view_class,
                kwargs=rm.kwargs,
                url_name=rm.url_name,
                namespaces=[self.namespace] + rm.namespaces,
                route=rm.route,
                is_catchall=rm.is_catchall,
            )

        # Priority:  specific ResolverMatch  >  SlashMismatch  >  catchall  >  None
        # Catchalls are held aside so they don't eat slash redirects from
        # specific siblings (the "shadow problem" — see `URLPattern.is_catchall`).
        # `is_catchall` is preserved through `_wrap` so the signal survives
        # arbitrary include nesting — a catchall inside `include("", X)`
        # still yields to an outer SlashMismatch.
        pending: SlashMismatch | None = None
        catchall: ResolverMatch | None = None
        for child in self.url_patterns:
            if isinstance(child, URLPattern):
                result = child.resolve(
                    remaining_segments, trailing_slash, merged_prefix, kwargs
                )
            else:
                result = child._resolve_segments(
                    remaining_segments, trailing_slash, merged_prefix, kwargs
                )

            if isinstance(result, ResolverMatch):
                if result.is_catchall:
                    if catchall is None:
                        catchall = _wrap(result)
                else:
                    return _wrap(result)
            elif isinstance(result, SlashMismatch) and pending is None:
                pending = result

        if pending is not None:
            return pending
        return catchall

    def reverse(
        self,
        lookup_view: type | str,
        prefix_segments: tuple[Segment, ...] = (),
        prefix_trailing_slash: bool = False,
        /,
        **kwargs: Any,
    ) -> str:
        """Build the URL for `lookup_view`.

        `prefix_segments` is prepended to each candidate's segment chain
        — used by `reverse()` during namespace walks, where the
        accumulated namespace prefix needs to land on the final URL.
        `prefix_trailing_slash` is the trailing-slash flag of that
        accumulated prefix; it's used as the canonical trailing slash
        when the endpoint contributes no segments of its own (the
        `path("")` inside `include("admin/", ...)` case).

        Both leading positional args are positional-only so a URL with
        `<str:prefix_segments>` / `<bool:prefix_trailing_slash>` can
        still pass kwargs without colliding with these parameters.
        """
        possibilities = self.reverse_dict.get(lookup_view, [])
        for full_segments, trailing_slash in possibilities:
            effective_ts = _effective_trailing_slash(
                full_segments, trailing_slash, prefix_trailing_slash
            )
            url = _try_reverse(prefix_segments + full_segments, effective_ts, kwargs)
            if url is not None:
                return url

        m = getattr(lookup_view, "__module__", None)
        n = getattr(lookup_view, "__name__", None)
        lookup_view_s = f"{m}.{n}" if m and n else lookup_view

        if possibilities:
            arg_msg = f"keyword arguments '{kwargs}'" if kwargs else "no arguments"
            msg = (
                f"Reverse for '{lookup_view_s}' with {arg_msg} not found. "
                f"{len(possibilities)} pattern(s) tried."
            )
        else:
            msg = (
                f"Reverse for '{lookup_view_s}' not found. "
                f"'{lookup_view_s}' is not a valid view function or pattern name."
            )
        raise NoReverseMatch(msg)


def _build_lookups(
    url_patterns: list[URLPattern | URLResolver],
) -> tuple[_ReverseLookups, _NamespaceLookups]:
    """Build reverse/namespace dicts from a list of children.

    Children that are `URLResolver`s must already have their own
    `reverse_dict`/`namespace_dict` populated — they did so in their own
    `__init__`. This is just a single-level merge.

    Reverse iteration of `url_patterns` puts the latest-defined entry at
    the front of each list, so `reverse()` (which returns the first
    kwargs-matching entry) prefers the latest definition when multiple
    patterns share a name — matching Django's conventional reverse
    priority.
    """
    lookups: _ReverseLookups = {}
    namespaces: _NamespaceLookups = {}
    for url_pattern in reversed(url_patterns):
        if isinstance(url_pattern, URLPattern):
            _collect_endpoint(url_pattern, lookups)
        else:
            _collect_resolver(url_pattern, lookups, namespaces)
    return lookups, namespaces


def _collect_endpoint(url_pattern: URLPattern, lookups: _ReverseLookups) -> None:
    """Add a URLPattern's reverse data to `lookups`, keyed by view class and name.

    `reverse()` accepts either a view class or a name string, so the same
    dict serves both lookups — hence the heterogeneous key types.
    """
    entry: _ReverseEntry = (
        url_pattern.route.segments,
        url_pattern.route.trailing_slash,
    )
    lookups.setdefault(url_pattern.view_class, []).append(entry)
    if url_pattern.name:
        lookups.setdefault(url_pattern.name, []).append(entry)


def _collect_resolver(
    url_pattern: URLResolver,
    lookups: _ReverseLookups,
    namespaces: _NamespaceLookups,
) -> None:
    """Merge a child URLResolver's pre-built reverse data into the parent's lookups.

    Namespaced children become entries in `namespaces` keyed by namespace;
    un-namespaced children's entries are folded into `lookups` with the
    child's prefix prepended.
    """
    child_prefix = url_pattern.route.segments
    child_trailing_slash = url_pattern.route.trailing_slash
    if url_pattern.namespace:
        _register_namespace(
            namespaces,
            url_pattern.namespace,
            child_prefix,
            child_trailing_slash,
            url_pattern,
        )
        return

    for name, entries in url_pattern.reverse_dict.items():
        for sub_segments, sub_trailing_slash in entries:
            effective_ts = _effective_trailing_slash(
                sub_segments, sub_trailing_slash, child_trailing_slash
            )
            lookups.setdefault(name, []).append(
                (child_prefix + sub_segments, effective_ts)
            )
    for ns_name, (ns_prefix, ns_ts, ns_resolver) in url_pattern.namespace_dict.items():
        # The merged-prefix's trailing slash: inner wins if it contributed
        # segments, otherwise inherit the outer's. Same rule as endpoint
        # merging above — without this, reverse() would read the inner
        # resolver's own route slash and miss the outer's.
        merged_ts = _effective_trailing_slash(ns_prefix, ns_ts, child_trailing_slash)
        _register_namespace(
            namespaces, ns_name, child_prefix + ns_prefix, merged_ts, ns_resolver
        )


def _register_namespace(
    namespaces: _NamespaceLookups,
    ns_name: str,
    prefix_segments: tuple[Segment, ...],
    prefix_trailing_slash: bool,
    resolver: URLResolver,
) -> None:
    """Assign a namespace entry, refusing to overwrite an existing one.

    Two `include()`s exposing the same namespace under one parent is
    always a mistake — one is unreachable via `reverse()` no matter
    which precedence we pick. Fail loudly at registration so the
    typo/copy-paste surfaces in the diff that introduced it.
    """
    if ns_name in namespaces:
        raise ImproperlyConfigured(
            f"Namespace '{ns_name}' is registered by more than one include() "
            "under the same parent router. Give each include() a unique namespace."
        )
    namespaces[ns_name] = (prefix_segments, prefix_trailing_slash, resolver)


def _try_reverse(
    full_segments: tuple[Segment, ...],
    trailing_slash: bool,
    kwargs: dict[str, Any],
) -> str | None:
    """Try to build a URL from a full segment chain and kwargs.

    Returns None if kwargs don't match the parameter names or if a
    converter's `to_url` produces a value that doesn't match the
    converter's own regex.
    """
    param_names = {cap.name for cap in _captures_in(full_segments)}
    if set(kwargs) != param_names:
        return None

    parts: list[str] = []
    for seg in full_segments:
        rendered = _reverse_segment(seg, kwargs)
        if rendered is None:
            return None
        parts.append(rendered)

    body = "/".join(parts)
    url = f"/{body}" if body else "/"
    if trailing_slash and body:
        url += "/"
    return escape_leading_slashes(quote(url, safe=RFC3986_SUBDELIMS + "/~:@"))


def _reverse_segment(seg: Segment, kwargs: dict[str, Any]) -> str | None:
    """Render one segment for reverse(). Returns None on validation failure."""
    if isinstance(seg, Literal):
        return seg.value
    if isinstance(seg, Capture):
        return _reverse_capture(seg, kwargs)
    # Pattern — render each part inline
    rendered_parts: list[str] = []
    for part in seg.parts:
        if isinstance(part, Literal):
            rendered_parts.append(part.value)
            continue
        rendered = _reverse_capture(part, kwargs)
        if rendered is None:
            return None
        rendered_parts.append(rendered)
    return "".join(rendered_parts)


def _reverse_capture(cap: Capture, kwargs: dict[str, Any]) -> str | None:
    """Convert + validate one captured value for reverse()."""
    try:
        url_value = cap.converter.to_url(kwargs[cap.name])
    except (ValueError, TypeError):
        return None
    if not _segment_value_matches(cap.converter, url_value):
        return None
    return url_value
