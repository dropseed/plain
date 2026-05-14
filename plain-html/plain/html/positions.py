"""Body-offset → file (line, col) conversions.

The tokenizer records byte offsets into the template *body* (post-
frontmatter). For diagnostics we want positions inside the original
source file. This module is the single place that maps between the two.
"""

from __future__ import annotations


def body_offset(source: str) -> int:
    """Return the byte offset where the template body starts in `source`.

    Mirrors python-frontmatter's `---\\n…\\n---\\n` delimiter handling so
    error positions map back to file positions even when frontmatter is
    present.
    """
    if not source.startswith("---\n"):
        return 0
    i = 4
    while i < len(source):
        end = source.find("\n", i)
        if end == -1:
            return 0
        if source[i:end].strip() == "---":
            return end + 1
        i = end + 1
    return 0


def offset_to_line_col(source: str, offset: int) -> tuple[int, int]:
    """Convert a 0-based byte offset in `source` to 1-based (line, column)."""
    if offset < 0:
        offset = 0
    if offset > len(source):
        offset = len(source)
    head = source[:offset]
    line = head.count("\n") + 1
    last_newline = head.rfind("\n")
    col = offset - last_newline if last_newline >= 0 else offset + 1
    return line, col
