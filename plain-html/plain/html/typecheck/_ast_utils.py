"""AST helpers shared across typecheck submodules."""

from __future__ import annotations

import ast


def dotted_chain(node: ast.AST) -> list[str] | None:
    """Return `["a", "b", "c"]` for `a.b.c`, or None if the chain isn't
    rooted at a plain Name (e.g. `func().attr`).
    """
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return parts
