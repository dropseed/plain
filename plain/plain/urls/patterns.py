from __future__ import annotations

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

        Returns:
            ResolverMatch — exact match (segments + trailing_slash agree)
            SlashMismatch — segments matched, trailing_slash didn't
            None — segments didn't match
        """
        match = _walk_segments(self.route.segments, segments, full_match=True)
        if match is None:
            return None
        _, captured = match

        effective_trailing_slash = _effective_trailing_slash(
            self.route.segments,
            self.route.trailing_slash,
            # Any non-empty prefix means we're under at least one `include()`,
            # which always normalizes to a trailing slash separator.
            ancestor_trailing_slash=bool(prefix_segments),
        )

        if trailing_slash == effective_trailing_slash:
            kwargs = {**prefix_kwargs, **captured} if captured else prefix_kwargs
            return ResolverMatch(
                view_class=self.view_class,
                kwargs=kwargs,
                url_name=self.name,
                route=_route_str(
                    prefix_segments + self.route.segments, effective_trailing_slash
                ),
            )

        return SlashMismatch()


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
