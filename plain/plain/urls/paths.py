"""Request-path parsing and canonical-form normalization.

`_parse_path` is the single source of truth for what shape a request
path reaches the resolver in. It:

- Rejects malformed paths (`..` below root) as `BadPath` → 400.
- Detects non-canonical inputs (`//`, `.`, `..`) and asks the client to
  redirect via `RedirectToCanonical` → 308.
- Splits canonical inputs into a `ParsedPath` (segments + trailing-slash
  flag) for the resolver to walk.

`URLPattern.resolve` separately reports `SlashMismatch` when the request
matches a route's segments but disagrees on the trailing-slash form. The
resolver answers that by toggling the slash on the *original* request
path — not by re-rendering the matched route — so that opaque captured
values (e.g. `<int:id>` matching `001`) round-trip unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedPath:
    """A request path, split into segments and stripped of trailing slash.

    Segments are the literal `/`-delimited components of the URL after
    `_parse_path` has resolved any `.` / `..` and collapsed any empty
    segments. `trailing_slash` carries whether the canonical form ends
    with `/`. The path is root iff `segments == ()`.
    """

    segments: tuple[str, ...]
    trailing_slash: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RedirectToCanonical:
    """The request was non-canonical at the *path* level (`//`, `.`,
    `..`) — client should redirect to `canonical`. Produced only by
    `_parse_path`; route-level trailing-slash mismatches use the lighter
    `SlashMismatch` signal so that captured values aren't re-rendered.
    """

    canonical: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SlashMismatch:
    """The request matched a route's segments but disagreed on the
    trailing slash. No canonical form is carried — the resolver toggles
    the slash on the original request path text, preserving the user's
    exact characters (so `/items/001` redirects to `/items/001/`, not
    to `/items/1/` as `<int:id>.to_url()` would render).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class BadPath:
    """`_parse_path` rejected the input as malformed (e.g. `..` below root)."""

    reason: str


def _has_dot_segment(path: str) -> bool:
    """Whether `path` contains a `.` or `..` segment.

    Looks for `/./`, `/../`, or a trailing `/.`/`/..`. Avoids matching
    paths that just contain a dot inside a segment (e.g. `/file.txt`).
    """
    return (
        "/./" in path or "/../" in path or path.endswith("/.") or path.endswith("/..")
    )


def _parse_path(path: str) -> ParsedPath | RedirectToCanonical | BadPath:
    """Normalize a request path string and split it into segments.

    Per RFC 3986 §5.2.4: `.` segments are dropped, `..` pops the previous
    segment. Consecutive `/` produces empty segments which are dropped
    (Phoenix/Rails behavior — but visible to clients via 308 redirect to
    the collapsed form). `..` that would pop below the root returns
    `BadPath` so the framework can answer with 400.

    Returns `RedirectToCanonical` when the input differed from the
    canonical form (any normalization happened). Returns `ParsedPath`
    when the input was already canonical.
    """
    if not path.startswith("/"):
        return BadPath(reason="Request path must start with `/`.")

    # Fast path: canonical inputs (no `//`, no `.`/`..` segments) skip the
    # rebuild + comparison entirely. Most production traffic lands here.
    if "//" not in path and not _has_dot_segment(path):
        # Root case is special: `"/"[1:-1].split("/")` produces `[""]`, not
        # `[]`, so we'd return a phantom empty segment without this guard.
        if path == "/":
            return ParsedPath(segments=(), trailing_slash=False)
        trailing_slash = path.endswith("/")
        body = path[1:-1] if trailing_slash else path[1:]
        return ParsedPath(
            segments=tuple(body.split("/")), trailing_slash=trailing_slash
        )

    raw = path[1:]
    raw_trailing_slash = raw.endswith("/") if raw else False
    raw_segments = raw.split("/") if raw else []

    segments: list[str] = []
    for seg in raw_segments:
        if seg == "":
            # `//` produces an empty segment — dropped, but signals
            # normalization needed.
            continue
        if seg == ".":
            continue
        if seg == "..":
            if not segments:
                return BadPath(
                    reason="URL contained `..` segments that would resolve below the root."
                )
            segments.pop()
            continue
        segments.append(seg)

    # A `.` or `..` as the leaf segment implies directory semantics —
    # the canonical form has a trailing slash. A dot segment in the
    # middle (`/foo/./bar`) just disappears and doesn't affect the
    # trailing-slash question.
    leaf_was_dot_segment = bool(raw_segments) and raw_segments[-1] in (".", "..")
    trailing_slash = raw_trailing_slash or leaf_was_dot_segment

    canonical = "/" + "/".join(segments)
    if trailing_slash and segments:
        canonical += "/"

    if canonical != path:
        return RedirectToCanonical(canonical=canonical)

    # Root has no meaningful trailing-slash form; normalize to False.
    if not segments:
        trailing_slash = False

    return ParsedPath(segments=tuple(segments), trailing_slash=trailing_slash)
