from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def _identity(value: Any) -> Any:
    return value


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Converter:
    """A URL path-parameter converter.

    `keyword` is the form used in patterns: `<keyword:name>`.
    `regex` validates a segment value at match and reverse time.
    `to_python` types the captured value.
    `to_url` stringifies a value back for `reverse()`.
    `multi_segment` opts the converter into matching across `/` —
    the matcher joins all remaining path segments and passes the
    result as the captured value. A multi-segment converter may
    only appear as the terminal segment of a route.

    `eq=False` keeps equality as identity. Converters are module-level
    singletons (`INT`, `STR`, ...); structural equality on `Callable`
    fields would compare function identities anyway, so identity is
    both simpler and the actual semantic.
    """

    keyword: str
    regex: str
    to_python: Callable[[str], Any]
    to_url: Callable[[Any], str]
    multi_segment: bool = False


INT = Converter(keyword="int", regex="[0-9]+", to_python=int, to_url=str)
STR = Converter(keyword="str", regex="[^/]+", to_python=_identity, to_url=str)
SLUG = Converter(
    keyword="slug", regex="[-a-zA-Z0-9_]+", to_python=_identity, to_url=str
)
PATH = Converter(
    keyword="path",
    # `[\s\S]+` instead of `.+` so a captured segment containing `\n` still
    # matches. Plain compiles segment regexes without `re.DOTALL`, and a
    # bare `.` would silently reject newline-bearing paths — which catch-all
    # routes (`path("<path:_>", JsonNotFoundView)`) need to handle uniformly.
    regex=r"[\s\S]+",
    to_python=_identity,
    to_url=str,
    multi_segment=True,
)
UUID = Converter(
    keyword="uuid",
    regex="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    to_python=uuid.UUID,
    to_url=str,
)


_CONVERTERS: dict[str, Converter] = {c.keyword: c for c in (INT, STR, SLUG, PATH, UUID)}


def _get_converter(name: str) -> Converter:
    return _CONVERTERS[name]
