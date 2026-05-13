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
    Segment,
    _captures_in,
    _route_to_segments,
    _segment_value_matches,
    _walk_segments,
)

if TYPE_CHECKING:
    from .routers import Router


# Reverse-lookup entries map a key (view class or name string) to a list
# of candidate (segments, endpoint) pairs. The endpoint's `trailing_slash`
# property (which reads `URLS_TRAILING_SLASH` + per-route override) is
# queried at reverse() time so a settings flip is observed without a
# rebuild of the lookup tuple.
_ReverseEntry = tuple[tuple[Segment, ...], URLPattern]
_ReverseLookups = dict[type | str, list[_ReverseEntry]]
# Namespace entries map a namespace string to its prefix segments and
# the resolver that owns them. No prefix slash flag — includes don't
# carry one in the new model.
_NamespaceEntry = tuple[tuple[Segment, ...], "URLResolver"]
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

    return URLResolver(segments=_route_to_segments(""), raw_route="", router=router)


class URLResolver:
    """A prefix-matcher: matches a segment prefix against incoming
    request segments, then dispatches to its children (URLPatterns or
    nested URLResolvers).
    """

    def __init__(
        self,
        *,
        segments: tuple[Segment, ...],
        raw_route: str,
        router: Router,
    ):
        self.segments = segments
        self.raw_route = raw_route
        self.router = router
        self.namespace = router.namespace
        self.url_patterns = router.urls

        # Eager merge: each child URLResolver already built its own dicts
        # during its own __init__. The URL graph is a DAG constructed
        # bottom-up at include() time, so a child never references its
        # parent — no recursion, no cycle handling needed.
        self.reverse_dict: _ReverseLookups = {}
        self.namespace_dict: _NamespaceLookups = {}
        self._build_lookups()

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
        match = _walk_segments(self.segments, segments, full_match=False)
        if match is None:
            return None
        consumed, captured = match
        kwargs = {**prefix_kwargs, **captured} if captured else prefix_kwargs
        remaining_segments = segments[consumed:]
        merged_prefix = prefix_segments + self.segments

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
                    remaining_segments,
                    trailing_slash,
                    merged_prefix,
                    kwargs,
                )
            else:
                result = child._resolve_segments(
                    remaining_segments,
                    trailing_slash,
                    merged_prefix,
                    kwargs,
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
        /,
        **kwargs: Any,
    ) -> str:
        """Build the URL for `lookup_view`.

        `prefix_segments` is prepended to each candidate's segment chain
        — used by `reverse()` during namespace walks, where the
        accumulated namespace prefix needs to land on the final URL.
        Positional-only so a URL with `<str:prefix_segments>` can still
        pass kwargs without colliding.
        """
        possibilities = self.reverse_dict.get(lookup_view, [])
        for full_segments, endpoint in possibilities:
            url = self._try_reverse(
                prefix_segments + full_segments, endpoint.trailing_slash, kwargs
            )
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

    # ------------------------------------------------------------------
    # Lookup table construction
    # ------------------------------------------------------------------

    def _build_lookups(self) -> None:
        """Populate `self.reverse_dict` and `self.namespace_dict` from
        `self.url_patterns`.

        Children that are `URLResolver`s must already have their own
        `reverse_dict`/`namespace_dict` populated — they did so in their
        own `__init__`. This is a single-level merge.

        Reverse iteration of `url_patterns` puts the latest-defined entry
        at the front of each list, so `reverse()` (which returns the first
        kwargs-matching entry) prefers the latest definition when multiple
        patterns share a name — matching Django's conventional reverse
        priority.
        """
        for url_pattern in reversed(self.url_patterns):
            if isinstance(url_pattern, URLPattern):
                self._collect_endpoint(url_pattern)
            else:
                self._collect_resolver(url_pattern)

    def _collect_endpoint(self, url_pattern: URLPattern) -> None:
        """Add a URLPattern's reverse data, keyed by view class and name.

        `reverse()` accepts either a view class or a name string, so the
        same dict serves both lookups — hence the heterogeneous key types.
        """
        entry: _ReverseEntry = (url_pattern.segments, url_pattern)
        self.reverse_dict.setdefault(url_pattern.view_class, []).append(entry)
        if url_pattern.name:
            self.reverse_dict.setdefault(url_pattern.name, []).append(entry)

    def _collect_resolver(self, url_pattern: URLResolver) -> None:
        """Merge a child URLResolver's pre-built reverse data.

        Namespaced children become entries in `namespace_dict`;
        un-namespaced children's entries are folded into `reverse_dict`
        with the child's prefix prepended.
        """
        child_prefix = url_pattern.segments
        if url_pattern.namespace:
            self._register_namespace(url_pattern.namespace, child_prefix, url_pattern)
            return

        for name, entries in url_pattern.reverse_dict.items():
            for sub_segments, sub_endpoint in entries:
                self.reverse_dict.setdefault(name, []).append(
                    (child_prefix + sub_segments, sub_endpoint)
                )
        for ns_name, (ns_prefix, ns_resolver) in url_pattern.namespace_dict.items():
            self._register_namespace(ns_name, child_prefix + ns_prefix, ns_resolver)

    def _register_namespace(
        self,
        ns_name: str,
        prefix_segments: tuple[Segment, ...],
        resolver: URLResolver,
    ) -> None:
        """Assign a namespace entry, refusing to overwrite an existing one.

        Two `include()`s exposing the same namespace under one parent is
        always a mistake — one is unreachable via `reverse()` no matter
        which precedence we pick. Fail loudly at registration so the
        typo/copy-paste surfaces in the diff that introduced it.
        """
        if ns_name in self.namespace_dict:
            raise ImproperlyConfigured(
                f"Namespace '{ns_name}' is registered by more than one include() "
                "under the same parent router. Give each include() a unique namespace."
            )
        self.namespace_dict[ns_name] = (prefix_segments, resolver)

    # ------------------------------------------------------------------
    # Reverse URL construction
    # ------------------------------------------------------------------

    @staticmethod
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
            rendered = URLResolver._reverse_segment(seg, kwargs)
            if rendered is None:
                return None
            parts.append(rendered)

        body = "/".join(parts)
        url = f"/{body}" if body else "/"
        if trailing_slash and body:
            url += "/"
        return escape_leading_slashes(quote(url, safe=RFC3986_SUBDELIMS + "/~:@"))

    @staticmethod
    def _reverse_segment(seg: Segment, kwargs: dict[str, Any]) -> str | None:
        """Render one segment for reverse(). Returns None on validation failure."""
        if isinstance(seg, Literal):
            return seg.value
        if isinstance(seg, Capture):
            return URLResolver._reverse_capture(seg, kwargs)
        # Pattern — render each part inline
        rendered_parts: list[str] = []
        for part in seg.parts:
            if isinstance(part, Literal):
                rendered_parts.append(part.value)
                continue
            rendered = URLResolver._reverse_capture(part, kwargs)
            if rendered is None:
                return None
            rendered_parts.append(rendered)
        return "".join(rendered_parts)

    @staticmethod
    def _reverse_capture(cap: Capture, kwargs: dict[str, Any]) -> str | None:
        """Convert + validate one captured value for reverse()."""
        try:
            url_value = cap.converter.to_url(kwargs[cap.name])
        except (ValueError, TypeError):
            return None
        if not _segment_value_matches(cap.converter, url_value):
            return None
        return url_value
