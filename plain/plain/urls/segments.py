"""Segment-based route representation and matcher.

Routes are parsed into ordered tuples of `Literal | Capture` segments.
`_walk_segments` walks a route's segments against a request's path
segments (produced by `paths._parse_path`), capturing converter values.

Converters still expose a `regex` attribute, which is used to validate
the *value* within a single segment — not as a slice of the URL.
"""

from __future__ import annotations

import functools
import re
import string
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.utils.regex_helper import _lazy_re_compile

from .converters import Converter, _get_converter


@dataclass(frozen=True, slots=True, kw_only=True)
class Literal:
    """A literal URL segment (e.g. `users` in `users/<int:id>/`)."""

    value: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Capture:
    """A typed capture (e.g. `<int:id>` or `<path:rest>`).

    `converter.multi_segment` determines whether the capture consumes a
    single path segment or all remaining segments joined by `/`.
    A multi-segment capture must be the terminal segment of a route.
    """

    name: str
    converter: Converter


# A `Pattern.parts` element. Pattern can't contain another Pattern (nesting
# is one level deep) and can't contain a multi-segment Capture (those span
# segment boundaries, which contradicts per-segment match) — the parser
# enforces both invariants at construction time.
PatternPart = Literal | Capture


@dataclass(frozen=True, slots=True, kw_only=True)
class Pattern:
    """A segment with mixed literal text and one or more captures.

    Example: `<slug:form_slug>.js` parses to a Pattern with parts
    `(Capture("form_slug", SLUG), Literal(".js"))`. Match builds a regex
    from the parts and applies it to the segment value; reverse walks
    the parts and interpolates converter values into the literal frame.
    """

    parts: tuple[PatternPart, ...]


Segment = Literal | Capture | Pattern


@dataclass(frozen=True, slots=True, kw_only=True)
class Route:
    """Parsed route from `path()` or `include()`.

    `trailing_slash` is meaningful for endpoints (from `path()`); for
    include prefixes it always describes whether there's a separator
    before the child segments and is enforced by the parser/constructor.
    """

    segments: tuple[Segment, ...]
    trailing_slash: bool

    @property
    def converters(self) -> dict[str, Converter]:
        """Names → converter for every capture, including those inside Patterns."""
        return {cap.name: cap.converter for cap in _captures_in(self.segments)}


def _captures_in(segments: tuple[Segment, ...]) -> Iterator[Capture]:
    """Yield every `Capture` in a segment chain, descending into Patterns."""
    for seg in segments:
        if isinstance(seg, Capture):
            yield seg
        elif isinstance(seg, Pattern):
            for part in seg.parts:
                if isinstance(part, Capture):
                    yield part


def _effective_trailing_slash(
    endpoint_segments: tuple[Segment, ...],
    endpoint_trailing_slash: bool,
    ancestor_trailing_slash: bool,
) -> bool:
    """Whether the canonical URL for this match ends with `/`.

    Rule: if the endpoint contributed any segments of its own, its
    trailing-slash flag wins. Otherwise (e.g. `path("")` inside
    `include("admin/", ...)`), inherit the ancestor's flag — so the
    canonical URL is the include's `/admin/`, not the endpoint's `/admin`.
    Applies at match time (`URLPattern.resolve`), at `reverse()` build
    time, and at lookup-table merge time (`_collect_resolver`).
    """
    return endpoint_trailing_slash if endpoint_segments else ancestor_trailing_slash


_PATH_PARAMETER_COMPONENT_RE = _lazy_re_compile(
    r"<(?:(?P<converter>[^>:]+):)?(?P<parameter>[^>]+)>"
)


def _route_to_segments(route: str) -> Route:
    """Parse a route string into a `Route`.

    Examples:
        `users/<int:id>/` → segments=(Literal("users"), Capture("id", INT)),
                            trailing_slash=True
        `admin` (include prefix) → segments=(Literal("admin"),), trailing_slash=False
        `<path:rest>` → segments=(Capture("rest", PATH),), trailing_slash=False
        `""` (root) → segments=(), trailing_slash=False
    """
    original_route = route

    if "?" in route or "#" in route:
        raise ImproperlyConfigured(
            f"URL route '{original_route}' contains '?' or '#'. Those "
            "characters separate the path from the query string and "
            "fragment in URLs and can't appear in route patterns."
        )

    trailing_slash = route.endswith("/")
    if trailing_slash:
        route = route[:-1]

    if route == "":
        return Route(segments=(), trailing_slash=trailing_slash)

    segments: list[Segment] = [
        _parse_segment(raw, original_route) for raw in route.split("/")
    ]

    for i, seg in enumerate(segments):
        if (
            isinstance(seg, Capture)
            and seg.converter.multi_segment
            and i != len(segments) - 1
        ):
            raise ImproperlyConfigured(
                f"URL route '{original_route}' has a multi-segment capture "
                f"`<{seg.converter.keyword}:{seg.name}>` that isn't the last "
                "segment. Multi-segment captures must be terminal."
            )

    seen_names: set[str] = set()
    for cap in _captures_in(tuple(segments)):
        if cap.name in seen_names:
            raise ImproperlyConfigured(
                f"URL route '{original_route}' uses parameter name "
                f"'{cap.name}' more than once. Each `<...>` capture in a "
                "route must have a unique name."
            )
        seen_names.add(cap.name)

    return Route(segments=tuple(segments), trailing_slash=trailing_slash)


def _parse_segment(raw: str, original_route: str) -> Segment:
    """Parse a single `/`-delimited segment into a `Segment`.

    A segment with no `<...>` is a `Literal`. A segment that is entirely
    one `<converter:name>` is a `Capture`. A segment with mixed literal
    text and captures (e.g. `<slug:x>.js`, `prefix-<int:id>`) is a
    `Pattern`.
    """
    if raw == "":
        # Reached here only via consecutive `/` in the route (entry points
        # in `routers.py` strip leading/trailing slashes). An empty Literal
        # never matches any path segment, so the pattern would be dead at
        # runtime — fail loudly at registration instead.
        raise ImproperlyConfigured(
            f"URL route '{original_route}' contains an empty segment "
            "(consecutive '/'). Each segment must have a non-empty literal "
            "or `<converter:name>` form."
        )

    matches = list(_PATH_PARAMETER_COMPONENT_RE.finditer(raw))
    if not matches:
        if "<" in raw or ">" in raw:
            raise ImproperlyConfigured(
                f"URL route '{original_route}' has segment '{raw}' with an "
                "unmatched '<' or '>'. Converter syntax requires `<converter:name>`."
            )
        return Literal(value=raw)

    parts: list[Literal | Capture] = []
    pos = 0
    for m in matches:
        if m.start() > pos:
            literal_text = raw[pos : m.start()]
            if "<" in literal_text or ">" in literal_text:
                raise ImproperlyConfigured(
                    f"URL route '{original_route}' has segment '{raw}' with an "
                    "unmatched '<' or '>'. Converter syntax requires "
                    "`<converter:name>`."
                )
            parts.append(Literal(value=literal_text))
        parts.append(_capture_from_match(m, original_route))
        pos = m.end()

    if pos < len(raw):
        trailing = raw[pos:]
        if "<" in trailing or ">" in trailing:
            raise ImproperlyConfigured(
                f"URL route '{original_route}' has segment '{raw}' with an "
                "unmatched '<' or '>'. Converter syntax requires `<converter:name>`."
            )
        parts.append(Literal(value=trailing))

    # Pure single Capture (no surrounding literal) collapses to Capture —
    # the common case stays simple, only mixed segments become Patterns.
    if len(parts) == 1 and isinstance(parts[0], Capture):
        return parts[0]

    # Multi-segment converters can't share a segment with literal text or
    # other captures — they consume across segment boundaries.
    for part in parts:
        if isinstance(part, Capture) and part.converter.multi_segment:
            raise ImproperlyConfigured(
                f"URL route '{original_route}' has multi-segment capture "
                f"`<{part.converter.keyword}:{part.name}>` mixed with literal "
                "text or other captures. Multi-segment captures must occupy "
                "their own segment."
            )

    return Pattern(parts=tuple(parts))


def _capture_from_match(match: re.Match[str], original_route: str) -> Capture:
    """Build a Capture from a `<converter:name>` regex match."""
    if not set(match.group()).isdisjoint(string.whitespace):
        raise ImproperlyConfigured(
            f"URL route '{original_route}' cannot contain whitespace in angle "
            "brackets <…>."
        )

    parameter = match["parameter"]
    if not parameter.isidentifier():
        raise ImproperlyConfigured(
            f"URL route '{original_route}' uses parameter name {parameter!r} "
            "which isn't a valid Python identifier."
        )

    raw_converter = match["converter"] or "str"
    try:
        converter = _get_converter(raw_converter)
    except KeyError as e:
        raise ImproperlyConfigured(
            f"URL route '{original_route}' uses invalid converter {raw_converter!r}."
        ) from e

    return Capture(name=parameter, converter=converter)


@functools.cache
def _compile_segment_pattern(regex: str) -> re.Pattern[str]:
    """Compile a per-segment anchored pattern from a converter's `regex`.

    `functools.cache` has internal locking, so insertion is safe under
    free-threaded Python — unlike a hand-rolled module-level dict.
    """
    return re.compile(rf"\A(?:{regex})\Z")


def _segment_value_matches(converter: Converter, value: str) -> bool:
    """Whether `value` matches the converter's `regex` end-to-end.

    Per-segment patterns are anchored so partial matches don't leak.
    """
    return _compile_segment_pattern(converter.regex).match(value) is not None


def _walk_segments(
    route_segments: tuple[Segment, ...],
    path_segments: tuple[str, ...],
    *,
    full_match: bool,
) -> tuple[int, dict[str, Any]] | None:
    """Walk `route_segments` against `path_segments`, capturing converters.

    Used by both endpoint matching (which requires full consumption of
    `path_segments`) and include-prefix matching (which leaves the
    remainder for child routers to consume).

    Returns `(consumed, captured)` on success — `consumed` is the count
    of path segments matched, `captured` is the dict of converter values.
    Returns None on any mismatch.

    A multi-segment `Capture` is always terminal and consumes all
    remaining path segments joined by `/`.
    """
    captured: dict[str, Any] = {}
    si = 0
    for seg in route_segments:
        if isinstance(seg, Literal):
            if si >= len(path_segments) or path_segments[si] != seg.value:
                return None
            si += 1
            continue

        if isinstance(seg, Pattern):
            if si >= len(path_segments):
                return None
            pattern_re = _compile_pattern_regex(seg.parts)
            match = pattern_re.fullmatch(path_segments[si])
            if match is None:
                return None
            for part in seg.parts:
                if isinstance(part, Capture):
                    try:
                        captured[part.name] = part.converter.to_python(
                            match.group(part.name)
                        )
                    except ValueError:
                        return None
            si += 1
            continue

        # Capture
        if seg.converter.multi_segment:
            value = "/".join(path_segments[si:])
        elif si < len(path_segments):
            value = path_segments[si]
        else:
            return None

        if not value or not _segment_value_matches(seg.converter, value):
            return None
        try:
            captured[seg.name] = seg.converter.to_python(value)
        except ValueError:
            return None

        if seg.converter.multi_segment:
            si = len(path_segments)
            break
        si += 1

    if full_match and si != len(path_segments):
        return None
    return si, captured


@functools.cache
def _compile_pattern_regex(parts: tuple[PatternPart, ...]) -> re.Pattern[str]:
    """Compile a `Pattern` segment's parts into an anchored regex with named groups.

    Cache keys are `parts` tuples, so every `Capture.converter` must be
    hashable — relied on by the module-level `INT`/`STR`/... singletons in
    `converters.py`. A future converter that adds an unhashable field would
    crash this cache.
    """
    pieces: list[str] = []
    for part in parts:
        if isinstance(part, Literal):
            pieces.append(re.escape(part.value))
        else:
            pieces.append(f"(?P<{part.name}>{part.converter.regex})")
    return re.compile(r"\A" + "".join(pieces) + r"\Z")
