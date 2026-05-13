from __future__ import annotations

from functools import cached_property
from typing import Any

from plain.preflight import PreflightResult

from .matches import ResolverMatch
from .paths import SlashMismatch
from .segments import (
    Capture,
    Literal,
    Route,
    Segment,
    _effective_trailing_slash,
    _walk_segments,
)


class URLPattern:
    """An endpoint: a parsed route + view class + optional name."""

    def __init__(
        self,
        *,
        route: Route,
        raw_route: str,
        name: str,
        view_class: type,
    ):
        self.route = route
        self.raw_route = raw_route
        self.name = name
        self.view_class = view_class

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._describe()}>"

    def _describe(self) -> str:
        description = f"'{self.raw_route}'"
        if self.name:
            description += f" [name='{self.name}']"
        return description

    @cached_property
    def is_catchall(self) -> bool:
        """True for `path("<path:NAME>")` — sole-segment terminal multi-segment,
        no trailing slash. The resolver gives these fallback semantics."""
        segs = self.route.segments
        return (
            not self.route.trailing_slash
            and len(segs) == 1
            and isinstance(segs[0], Capture)
            and segs[0].converter.multi_segment
        )

    def preflight(self) -> list[PreflightResult]:
        if self.name and ":" in self.name:
            return [
                PreflightResult(
                    fix=(
                        f"Your URL pattern {self._describe()} has a name "
                        "including a ':'. Remove the colon, to avoid ambiguous "
                        "namespace references."
                    ),
                    warning=True,
                    id="urls.pattern_name_contains_colon",
                )
            ]
        return []

    def resolve(
        self,
        segments: tuple[str, ...],
        trailing_slash: bool,
        prefix_segments: tuple[Segment, ...],
        prefix_kwargs: dict[str, Any],
    ) -> ResolverMatch | SlashMismatch | None:
        """Try matching the request against this endpoint.

        Returns `ResolverMatch` on full match, `SlashMismatch` when
        segments matched but the trailing slash didn't, or `None`. A
        catchall (see `is_catchall`) absorbs the trailing slash into the
        capture and never reports `SlashMismatch`; the yields-to-
        SlashMismatch behavior lives in `URLResolver._resolve_segments`.
        """
        match = _walk_segments(
            self.route.segments,
            segments,
            full_match=True,
            absorb_trailing_slash=self.is_catchall and trailing_slash,
        )
        if match is None:
            return None
        _, captured = match

        if self.is_catchall:
            route_ts = False
        else:
            route_ts = _effective_trailing_slash(
                self.route.segments,
                self.route.trailing_slash,
                # A non-empty prefix means we're under an `include()`, which
                # contributes its own slash separator.
                ancestor_trailing_slash=bool(prefix_segments),
            )
            if trailing_slash != route_ts:
                return SlashMismatch()

        kwargs = {**prefix_kwargs, **captured} if captured else prefix_kwargs
        return ResolverMatch(
            view_class=self.view_class,
            kwargs=kwargs,
            url_name=self.name,
            route=_route_str(prefix_segments + self.route.segments, route_ts),
            is_catchall=self.is_catchall,
        )


def _route_str(segments: tuple[Segment, ...], trailing_slash: bool) -> str:
    """Render a full segment chain as a route string for span attributes.

    Literals appear verbatim; captures appear as `<keyword:name>` so the
    span value is stable across requests with different captured values.
    Pattern segments render their parts inline.
    """
    body = "/".join(_route_str_segment(seg) for seg in segments)
    if trailing_slash and body:
        body += "/"
    return body


def _route_str_segment(seg: Segment) -> str:
    if isinstance(seg, Literal):
        return seg.value
    if isinstance(seg, Capture):
        return f"<{seg.converter.keyword}:{seg.name}>"
    # Pattern
    return "".join(
        part.value
        if isinstance(part, Literal)
        else f"<{part.converter.keyword}:{part.name}>"
        for part in seg.parts
    )
