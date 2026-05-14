"""Template rendering entry points.

`render(path)` reads + compiles + renders a `.html` file.
`render_source(source, *, source_path)` renders a source string,
optionally resolving `:include`s relative to a known path.

Both delegate to `plain.html.compiler` — the tree-walking interpreter
this module used to host has been removed. If you need to revert that
decision, the last commit on `plain-html` before the interpreter was
deleted has the implementation.
"""

from __future__ import annotations

import os
import types
from pathlib import Path

from .compiler import CompileSession, get_or_compile


def render(path: str | os.PathLike, context: dict | None = None) -> str:
    """Render a `.html` file from disk.

    Hits the process-wide cache (`compiler.get_or_compile`) so repeated
    renders of the same path skip compile cost; first-call cost is
    further amortized by the disk cache at `<project>/.plain/html/`.
    """
    return get_or_compile(Path(path))(**(context or {}))


def render_source(
    source: str,
    context: dict | None = None,
    *,
    source_path: Path | None = None,
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
        return render_fn(**ctx)

    # No path → no static-include resolution possible. One-shot in-memory
    # compile of just this source; dynamic includes still work because
    # the resolver lives in the runtime layer. No source mapping either —
    # there's no file for `linecache` to read.
    src = CompileSession().compile_string(source)
    mod = types.ModuleType(f"_plain_html_inline_{abs(hash(source))}")
    mod.__file__ = "<source>"
    code = compile(src, "<source>", "exec")
    exec(code, mod.__dict__)
    return mod.render(**ctx)
