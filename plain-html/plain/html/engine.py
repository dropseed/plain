"""Template rendering entry points.

`render(path)` reads + compiles + renders a `.html` file.
`render_source(source, *, source_path)` renders a source string,
optionally resolving `:include`s relative to a known path.
`render_text_source(source)` renders a non-HTML text template
(Markdown bodies). All delegate to `plain.html.compiler`.

Each HTML entry point takes an optional `fragment=` name. The template
renders in full either way — every loop iterates, every branch decides —
and the named `{% fragment %}` block's output is what comes back. That
"render everything, keep one region" rule is what makes a fragment
inside a `{% for %}` see exactly the scope it sees on a full render.
"""

from __future__ import annotations

import os
import types
from collections.abc import Callable
from pathlib import Path

from .compiler import CompileSession, get_or_compile


class FragmentNotFound(Exception):
    """`fragment=` named a `{% fragment %}` the render didn't produce."""


def _render_with_fragment(
    render_fn: Callable[..., str],
    context: dict,
    fragment: str,
    label: str,
) -> str:
    """Render fully, then return just `fragment`'s captured output."""
    captured: dict[str, str] = {}
    render_fn(_frag_capture=captured, **context)
    if fragment in captured:
        return captured[fragment]
    raise FragmentNotFound(_fragment_error(render_fn, fragment, captured, label))


def _fragment_error(
    render_fn: Callable[..., str],
    fragment: str,
    captured: dict[str, str],
    label: str,
) -> str:
    declared = render_fn.__globals__.get("__template_fragments__", ())
    rendered = sorted(captured)
    if rendered:
        return (
            f"{label} has no fragment named {fragment!r} — "
            f"this render produced: {', '.join(repr(n) for n in rendered)}"
        )
    if declared:
        return (
            f"{label} has no fragment named {fragment!r} — it declares "
            f"{', '.join(repr(n) for n in declared)}, and none of them were "
            f"reached on this render"
        )
    return f"{label} declares no `{{% fragment %}}` blocks"


def render(
    path: str | os.PathLike,
    context: dict | None = None,
    *,
    fragment: str | None = None,
) -> str:
    """Render a `.html` file from disk.

    Hits the process-wide cache (`compiler.get_or_compile`) so repeated
    renders of the same path skip compile cost; first-call cost is
    further amortized by the disk cache at `<project>/.plain/html/`.

    With `fragment`, returns only that `{% fragment %}` block's output.
    """
    render_fn = get_or_compile(Path(path))
    if fragment is None:
        return render_fn(**(context or {}))
    return _render_with_fragment(render_fn, context or {}, fragment, f"`{path}`")


def render_source(
    source: str,
    context: dict | None = None,
    *,
    source_path: Path | None = None,
    fragment: str | None = None,
) -> str:
    """Render a template source string.

    With `source_path`, `:include`s resolve relative to that file —
    used by `plain.pages` to render templates whose source is in
    memory (after Markdown preprocessing) but should still be able
    to include sibling files.
    """
    ctx = context or {}
    if source_path is not None:
        # Goes through CompileSession so static includes get topologically
        # resolved relative to source_path. Bypasses the process cache so
        # an in-memory source edit doesn't return a stale compile.
        render_fn = CompileSession(use_disk_cache=False).compile_path(
            Path(source_path), source_override=source
        )
        label = f"`{source_path}`"
    else:
        # No path → no static-include resolution possible. One-shot in-memory
        # compile of just this source; dynamic includes still work because
        # the resolver lives in the runtime layer. No source mapping either —
        # there's no file for `linecache` to read.
        src = CompileSession().compile_string(source)
        mod = types.ModuleType(f"_plain_html_inline_{abs(hash(source))}")
        mod.__file__ = "<source>"
        code = compile(src, "<source>", "exec")
        exec(code, mod.__dict__)  # noqa: S102 — the engine's own generated module
        render_fn = mod.render
        label = "this template source"

    if fragment is None:
        return render_fn(**ctx)
    return _render_with_fragment(render_fn, ctx, fragment, label)


def render_text_source(source: str, context: dict | None = None) -> str:
    """Render a non-HTML text template source string.

    Uses the text-mode pipeline: only `{{ expr }}`, `{% raw %}`, and
    `{# comment #}` are recognized — everything else (including `<`,
    HTML-looking tags, and other `{% … %}`) is literal text, and
    expressions are emitted unescaped.

    This is how `plain.pages` interpolates Markdown bodies. Markdown is
    not balanced HTML — placeholder text like `<name>`, autolinks, raw
    snippets in code fences — so it can't go through the HTML-aware
    `render` / `render_source`.
    """
    src = CompileSession().compile_text_string(source)
    mod = types.ModuleType(f"_plain_html_text_{abs(hash(source))}")
    mod.__file__ = "<text>"
    code = compile(src, "<text>", "exec")
    exec(code, mod.__dict__)  # noqa: S102 — the engine's own generated module
    return mod.render(**(context or {}))
