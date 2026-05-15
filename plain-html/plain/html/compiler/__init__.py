"""AOT compile a parsed tag tree to a Python `render(...)` function.

Module split:
  - `expressions` — AST rewriting of `{...}` expressions + import binding extraction
  - `security`    — URL-attr allow-list, event-handler refusal, mark_safe opt-in
  - `emit`        — codegen for the tag tree
  - `session`     — `:include`-graph walker + process-wide compiled-template cache

Supported template features: text (constant-folded), `{{ expr }}` in
text and attribute values, real elements, comments and doctype,
`{% if %}` / `{% for %}` control flow, frontmatter `attrs:` / `slots:` /
`imports:`, PascalCase component tags with attr passing, and slot
composition (default slot plus named `{% slot %}` routing).

Expressions are inlined as real Python sub-expressions: free `Name`
loads are AST-rewritten to `_ctx['name']` except for names bound by
`:for` targets, names imported via frontmatter, Python builtins, and
names locally bound by the expression itself (comp/lambda/walrus).

Literal-path includes are resolved at compile time. A `CompileSession`
walks the template graph depth-first and compiles each leaf before its
parent, so when the parent module is exec'd its `_inc_N` references
already point at compiled child render functions injected into module
globals. Expression-form includes (`:include={...}`) resolve at render
time and reuse the process-wide compiled-template cache.
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
    get_or_compile,
)

__all__ = [
    "CompileError",
    "CompileSession",
    "PathResolver",
    "clear_process_cache",
    "get_or_compile",
]
