"""Frontmatter parser.

Splits a `.plain` source file into ``(frontmatter_dict, body, body_line_offset)``.

Phase 0 scope: parse YAML if present, return body text. Type-reference
resolution and `imports:` execution belong in later phases.
"""

from __future__ import annotations

import yaml


class FrontmatterError(Exception):
    pass


def split(source: str) -> tuple[dict, str, int]:
    """Split a template source into (frontmatter, body, body_line_offset).

    If the source begins with ``---\\n``, everything up to the next ``\\n---``
    line is parsed as YAML. Otherwise the whole source is body and frontmatter
    is empty.
    """
    if not source.startswith("---\n") and not source.startswith("---\r\n"):
        return {}, source, 0

    lines = source.splitlines(keepends=True)
    # First line is "---"; find the closing "---".
    closing = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            closing = i
            break
    if closing is None:
        raise FrontmatterError("Unterminated frontmatter: missing closing '---'")

    yaml_text = "".join(lines[1:closing])
    body = "".join(lines[closing + 1 :])
    body_line_offset = closing + 1

    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(f"Frontmatter YAML error: {e}") from e

    if not isinstance(data, dict):
        raise FrontmatterError("Frontmatter must be a YAML mapping")

    return data, body, body_line_offset
