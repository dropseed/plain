"""Type checking for `.html` templates.

`plain html check --typecheck` synthesizes a Python module from each
template's frontmatter + body, runs an external type checker (ty by
default, pyright as a fallback) against it, and maps diagnostics back to
template positions.
"""

from __future__ import annotations

from .checker import TypecheckError, check_path, check_source

__all__ = ["TypecheckError", "check_path", "check_source"]
