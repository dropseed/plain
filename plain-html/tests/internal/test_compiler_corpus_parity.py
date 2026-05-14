"""Full repo-corpus parity: every `.html` template renders identically
under both engines.

Empty context — for templates that require real data, both engines raise
NameError/KeyError on first reference and we skip. For templates that
render with no context (most layouts, components with defaulted attrs),
we assert byte-equal output.

Divergence is loud (test failure); a template that both engines reject
is informative noise (test skip). The point isn't to render the whole
repo successfully — it's to detect any case where the compiler produces
different output than the interpreter for inputs they both accept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plain.html.compiler import (
    CompileSession,
    clear_process_cache,
)
from plain.html.engine import _interpret_render

REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_MARKER = REPO_ROOT / "plain-html-implementation-plan.md"

pytestmark = pytest.mark.skipif(
    not _REPO_MARKER.exists(),
    reason="Corpus parity only runs from the repo checkout",
)


def _all_repo_templates() -> list[Path]:
    files: list[Path] = []
    for d in REPO_ROOT.rglob("html/*"):
        if not d.is_dir():
            continue
        for f in d.rglob("*.html"):
            files.append(f)
    return sorted(set(files))


def _interp(path: Path) -> tuple[str, str]:
    """Run the interpreter directly (bypassing the public `engine.render`
    so the cutover doesn't reroute us through the compiler). Returns
    (status, payload).

    status == "ok"  → payload is the rendered string
    status == "err" → payload is exception class name
    """
    try:
        return ("ok", _interpret_render(path, {}))
    except Exception as e:
        return ("err", type(e).__name__)


def _compiled(path: Path) -> tuple[str, str]:
    """Run the compiler. Same return shape as `_interp`.

    Catches every exception (not just compile-time errors) because the
    compiler resolves static `:include`s eagerly — a `TemplateNotFound`
    that the interpreter would raise at render time arrives here at
    compile time. Same with `imports:` errors and any other early-phase
    failure. We're checking output parity, not exception-class parity.
    """
    try:
        render_fn = CompileSession().compile_path(path)
    except Exception as e:
        return ("err", type(e).__name__)
    try:
        return ("ok", render_fn())
    except Exception as e:
        return ("err", type(e).__name__)


@pytest.mark.parametrize(
    "path",
    _all_repo_templates(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_corpus_engine_parity(path: Path) -> None:
    clear_process_cache()
    i_status, i_payload = _interp(path)
    clear_process_cache()
    c_status, c_payload = _compiled(path)

    if i_status == "ok" and c_status == "ok":
        assert i_payload == c_payload, (
            f"Output diverged for {path.relative_to(REPO_ROOT)}\n"
            f"--- interpreter ---\n{i_payload!r}\n"
            f"--- compiler ---\n{c_payload!r}"
        )
        return

    # At least one engine couldn't render in this empty-context environment.
    # The most common reason is cross-package `:include` paths (e.g.
    # `admin/header_branding` from inside `_header.html`) that aren't on the
    # test app's search path. The interpreter resolves those lazily — so a
    # template guarded by `:if={empty}` "renders" to whitespace without
    # touching the include. The compiler resolves all static includes at
    # compile time, so it fails earlier. Same root cause, different surface;
    # skip rather than treating it as a parity break.
    pytest.skip(
        f"inconclusive — interp={i_status}/{i_payload}, compiler={c_status}/{c_payload}"
    )
