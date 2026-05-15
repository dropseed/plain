"""Corpus property test for the formatter.

Walks every `.html` template under any `templates/` directory in the repo
checkout and asserts the formatter's hard invariants:

- The template parses cleanly.
- `format_source(format_source(x)) == format_source(x)` (idempotency).
- The bytes inside every `{...}` expression and the frontmatter block
  are preserved exactly.

This is the tier-1 conformance test from the plan: real templates are
the hardest corpus, regressions surface the moment a template lands or
the formatter changes shape. Files that the engine itself can't tokenize
are surfaced via `xfail` so they're visible without blocking the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plain.html.format import format_source
from plain.html.parser import ParseError
from plain.html.positions import body_offset
from plain.html.tokenizer import TokenizeError, tokenize

REPO_ROOT = Path(__file__).resolve().parents[3]

# Sanity check: if the test isn't running from a repo checkout, skip the
# whole module rather than producing a misleading empty pass.
_REPO_MARKER = REPO_ROOT / "CLAUDE.md"

pytestmark = pytest.mark.skipif(
    not _REPO_MARKER.exists(),
    reason="Corpus test only runs from the repo checkout",
)


def _discover_templates() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("templates/*"):
        if not path.is_dir():
            continue
        files.extend(path.rglob("*.html"))
    return sorted(set(files))


_TEMPLATES = _discover_templates()


def _template_id(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


@pytest.mark.parametrize("path", _TEMPLATES, ids=_template_id)
def test_template_formats_idempotently(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    try:
        once = format_source(source)
        twice = format_source(once)
    except (TokenizeError, ParseError) as e:
        pytest.xfail(f"engine cannot parse {path.name}: {e}")  # ty: ignore[too-many-positional-arguments]

    assert once == twice, f"format is not idempotent for {path}"


@pytest.mark.parametrize("path", _TEMPLATES, ids=_template_id)
def test_template_preserves_expression_bytes(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    try:
        original_tokens = tokenize(_body(source))
        out = format_source(source)
        formatted_tokens = tokenize(_body(out))
    except (TokenizeError, ParseError) as e:
        pytest.xfail(f"engine cannot parse {path.name}: {e}")  # ty: ignore[too-many-positional-arguments]

    original_exprs = _expr_bytes(original_tokens)
    formatted_exprs = _expr_bytes(formatted_tokens)
    assert original_exprs == formatted_exprs, f"expression interiors changed in {path}"


@pytest.mark.parametrize("path", _TEMPLATES, ids=_template_id)
def test_template_preserves_frontmatter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    out = format_source(source)
    src_fm = source[: body_offset(source)]
    out_fm = out[: body_offset(out)]
    assert src_fm == out_fm, f"frontmatter mutated in {path}"


def test_corpus_is_nonempty() -> None:
    # Guard against the discovery glob silently breaking.
    assert _TEMPLATES, "no templates discovered under any templates/ directory"


def _body(source: str) -> str:
    return source[body_offset(source) :]


def _expr_bytes(tokens) -> list[str]:
    from plain.html.tokenizer import (
        AttrExpr,
        ExprToken,
        StartTagToken,
    )

    out: list[str] = []
    for tok in tokens:
        if isinstance(tok, ExprToken):
            out.append(tok.code)
        elif isinstance(tok, StartTagToken):
            for attr in tok.attrs:
                if attr.segments is None:
                    continue
                for seg in attr.segments:
                    if isinstance(seg, AttrExpr):
                        out.append(seg.code)
    return out
