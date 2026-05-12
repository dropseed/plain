"""Frontmatter parser.

Delegates to the `python-frontmatter` package — same format `plain.pages`
already uses, so users see a consistent YAML-front-matter shape across the
framework. We only preserve the trailing newline that `frontmatter.parse`
drops, so the rendered output matches the source's final-line semantics.
"""

from __future__ import annotations

import frontmatter as _frontmatter


def split(source: str) -> tuple[dict, str]:
    """Split a `.plain` source into (frontmatter, body)."""
    metadata, body = _frontmatter.parse(source)
    if source.endswith("\n") and not body.endswith("\n"):
        body += "\n"
    return metadata, body
