"""AOT compile a parsed tag tree to a Python `render(...)` function.

Module split:
  - `expressions` — AST rewriting of `{...}` expressions + import binding extraction
  - `security`    — URL-attr allow-list, event-handler refusal, mark_safe opt-in
  - `emit`        — codegen for the tag tree
  - `session`     — `:include`-graph walker + process-wide compiled-template cache

Scope (phases 5a–5d):
  - Text (constant-folded), `{expr}`, elements, attributes.
  - `:if` / `:for` (real Python control flow).
  - `<template>` fragments + comments + doctype.
  - Frontmatter `attrs:` / `slots:` defaulting + `imports:` at module load.
  - `<template :include="literal/path">` with attr passing.
  - Slot composition: default slot + named (`slot="..."`) routing.

Expressions are inlined as real Python sub-expressions: free `Name`
loads are AST-rewritten to `_ctx['name']` except for names bound by
`:for` targets, names imported via frontmatter, Python builtins, and
names locally bound by the expression itself (comp/lambda/walrus).

Includes are resolved at compile time. A `CompileSession` walks the
template graph depth-first and compiles each leaf before its parent,
so when the parent module is exec'd its `_inc_N` references already
point at compiled child render functions injected into module globals.
"""

from __future__ import annotations


class CompileError(Exception):
    pass


# Defined-then-imported: session/emit do `from . import CompileError`, which
# resolves against the partially-initialized package module — the class above
# is in place by the time those imports run.
from .session import (  # noqa: E402
    CompileSession,
    PathResolver,
    clear_process_cache,
    compile_path,
    compile_source,
    compile_tree,
    get_or_compile,
)

__all__ = [
    "CompileError",
    "CompileSession",
    "PathResolver",
    "clear_process_cache",
    "compile_path",
    "compile_source",
    "compile_tree",
    "get_or_compile",
]
