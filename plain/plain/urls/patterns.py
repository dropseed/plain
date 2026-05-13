from __future__ import annotations

from functools import cached_property
from typing import Any

from plain.preflight import PreflightResult
from plain.runtime import settings

from .converters import Converter
from .matches import ResolverMatch
from .paths import SlashMismatch
from .segments import (
    Capture,
    Segment,
    _captures_in,
    _route_str,
    _segment_value_matches,
    _walk_segments,
)


class URLPattern:
    """An endpoint: a parsed segment chain + view class + optional name.

    The canonical trailing slash for this endpoint is given by
    `trailing_slash`, which reads `URLS_TRAILING_SLASH` unless the
    endpoint declares `force_trailing_slash=True|False`.
    """

    def __init__(
        self,
        *,
        segments: tuple[Segment, ...],
        raw_route: str,
        name: str,
        view_class: type,
        force_trailing_slash: bool | None = None,
    ):
        self.segments = segments
        self.raw_route = raw_route
        self.name = name
        self.view_class = view_class
        self.force_trailing_slash = force_trailing_slash

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._describe()}>"

    def _describe(self) -> str:
        description = f"'{self.raw_route}'"
        if self.name:
            description += f" [name='{self.name}']"
        return description

    @property
    def trailing_slash(self) -> bool:
        """Effective trailing-slash form for this endpoint.

        Catchalls absorb the request slash into the captured value;
        their canonical form has no trailing slash regardless of the
        setting. Otherwise per-route `force_trailing_slash` wins, then
        the app-wide `URLS_TRAILING_SLASH` setting. Reads live so a
        settings swap takes effect on the next resolver rebuild (tests
        clear `_get_cached_resolver.cache` to force one).

        Note: an endpoint with `segments=()` (a `path("", ...)`) may
        still report `True` here even though `/` itself has no
        slash variant — the resolver special-cases the "full URL is
        root" check at match time, since only then is the prefix
        context available."""
        if self.is_catchall:
            return False
        if self.force_trailing_slash is not None:
            return self.force_trailing_slash
        return settings.URLS_TRAILING_SLASH

    @cached_property
    def is_catchall(self) -> bool:
        """True for `path("<path:NAME>")` — sole-segment terminal
        multi-segment Capture. The resolver gives these fallback
        semantics (slash-agnostic match, yields to sibling
        `SlashMismatch`)."""
        return (
            len(self.segments) == 1
            and isinstance(self.segments[0], Capture)
            and self.segments[0].converter.multi_segment
        )

    @cached_property
    def converters(self) -> dict[str, Converter]:
        """Names → converter for every capture, including those inside Patterns."""
        return {cap.name: cap.converter for cap in _captures_in(self.segments)}

    def preflight(self) -> list[PreflightResult]:
        results: list[PreflightResult] = []
        if self.name and ":" in self.name:
            results.append(
                PreflightResult(
                    fix=(
                        f"Your URL pattern {self._describe()} has a name "
                        "including a ':'. Remove the colon, to avoid ambiguous "
                        "namespace references."
                    ),
                    warning=True,
                    id="urls.pattern_name_contains_colon",
                )
            )
        if self.is_catchall and self.force_trailing_slash is not None:
            results.append(
                PreflightResult(
                    fix=(
                        f"Your URL pattern {self._describe()} is a catchall "
                        "but sets `force_trailing_slash`. Catchalls absorb the "
                        "trailing slash into the captured value and ignore the "
                        "flag — remove `force_trailing_slash`."
                    ),
                    warning=True,
                    id="urls.catchall_force_trailing_slash",
                )
            )
        return results

    def resolve(
        self,
        segments: tuple[str, ...],
        trailing_slash: bool,
        prefix_segments: tuple[Segment, ...],
        prefix_kwargs: dict[str, Any],
    ) -> ResolverMatch | SlashMismatch | None:
        """Try matching the request against this endpoint.

        Returns `ResolverMatch` on full match, `SlashMismatch` when
        segments matched but the trailing slash didn't, or `None`.

        Catchalls take their own match path — slash-agnostic, absorb the
        trailing slash into the captured value, never report
        `SlashMismatch`. The yields-to-`SlashMismatch` behavior lives in
        `URLResolver._resolve_segments`.
        """
        if self.is_catchall:
            return self._resolve_catchall(
                segments, trailing_slash, prefix_segments, prefix_kwargs
            )

        match = _walk_segments(self.segments, segments, full_match=True)
        if match is None:
            return None
        _, captured = match

        full_segments = prefix_segments + self.segments
        # Root URL (`/`) has no alternate slash form — `_parse_path("/")`
        # always reports `trailing_slash=False`, so following the global
        # `URLS_TRAILING_SLASH=True` would 308-redirect to the empty
        # string. Skip the slash check when the full URL is root.
        if full_segments:
            route_ts = self.trailing_slash
            if trailing_slash != route_ts:
                return SlashMismatch()
        else:
            route_ts = False

        kwargs = {**prefix_kwargs, **captured} if captured else prefix_kwargs
        return ResolverMatch(
            view_class=self.view_class,
            kwargs=kwargs,
            url_name=self.name,
            route=_route_str(full_segments, route_ts),
        )

    def _resolve_catchall(
        self,
        segments: tuple[str, ...],
        trailing_slash: bool,
        prefix_segments: tuple[Segment, ...],
        prefix_kwargs: dict[str, Any],
    ) -> ResolverMatch | None:
        """Match a catchall (`path("<path:NAME>")`) against the request.

        The route has exactly one segment — a multi-segment `Capture`
        (guaranteed by `is_catchall`). Joins all request segments into
        the captured value, appending the trailing slash if present so
        a single declared route handles both `/missing` and `/missing/`.
        """
        cap = self.segments[0]
        assert isinstance(cap, Capture)

        value = "/".join(segments)
        if not value:
            return None
        if trailing_slash:
            value += "/"

        if not _segment_value_matches(cap.converter, value):
            return None
        try:
            captured_value = cap.converter.to_python(value)
        except ValueError:
            return None

        kwargs = {**prefix_kwargs, cap.name: captured_value}
        return ResolverMatch(
            view_class=self.view_class,
            kwargs=kwargs,
            url_name=self.name,
            route=_route_str(prefix_segments + self.segments, self.trailing_slash),
            is_catchall=True,
        )
