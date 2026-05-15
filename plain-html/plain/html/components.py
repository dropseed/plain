"""Parser for the `components:` frontmatter key.

A `components:` entry imports another template as a PascalCase component
tag. Each entry is a string — either a bare path (`"components/Card"`) or
a path with an explicit name (`"base as Base"`). The resolved tag name is
the last path segment, or the `as` target when given; it must be
PascalCase. The result is a `dict[name -> path_string]` the parser threads
into element construction so a `<Card>` tag reuses the `:include`
compile-graph backend.
"""

from __future__ import annotations

import re

_PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


class ComponentsError(Exception):
    """Raised for a malformed `components:` frontmatter declaration."""


def parse_components(raw: object) -> dict[str, str]:
    """Read the raw `components:` YAML value into a `dict[name -> path]`.

    `raw` is whatever `python-frontmatter` produced for the key (or `None`
    when the key is absent). Returns an empty dict when there's nothing to
    parse.
    """
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ComponentsError(
            f"`components:` must be a list of template paths, got {type(raw).__name__}"
        )

    out: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, str):
            raise ComponentsError(
                f"`components:` entries must be strings, got {type(entry).__name__}"
            )
        name, path = _parse_entry(entry)
        if name in out:
            raise ComponentsError(
                f"`components:` declares two entries resolving to the same "
                f"name `{name}`"
            )
        out[name] = path
    return out


def _parse_entry(entry: str) -> tuple[str, str]:
    """Resolve one `components:` entry into (tag_name, path_string)."""
    text = entry.strip()
    if not text:
        raise ComponentsError("`components:` entry cannot be empty")

    if " as " in text:
        path_part, _, name_part = text.partition(" as ")
        path = path_part.strip()
        name = name_part.strip()
        if not path or not name:
            raise ComponentsError(
                f"Invalid `components:` entry {entry!r} — expected "
                f"`path` or `path as Name`"
            )
    else:
        path = text
        name = path.rstrip("/").rsplit("/", 1)[-1]

    if not _PASCAL_CASE.match(name):
        raise ComponentsError(
            f"component name `{name}` (from `components:` entry {entry!r}) "
            f"must be PascalCase — matching `^[A-Z][A-Za-z0-9]*$`"
        )
    return name, path
