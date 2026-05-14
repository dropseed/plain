"""Performance regression guard for the formatter.

Plan target: format the full repo corpus in under 2 seconds and a
typical template in under 10 ms (warm). Current numbers are well under
both — this test asserts a generous budget so a 30×+ regression fails
CI without flaking on normal machine variance.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from plain.html.format import format_source
from plain.html.parser import ParseError
from plain.html.tokenizer import TokenizeError

REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_MARKER = REPO_ROOT / "plain-html-implementation-plan.md"

pytestmark = pytest.mark.skipif(
    not _REPO_MARKER.exists(),
    reason="Performance test only runs from the repo checkout",
)

# Generous compared to current ~33 ms; tight enough to catch a 30×+
# regression. CI machines vary; the budget needs slack.
CORPUS_BUDGET_SECONDS = 1.0


def _discover_sources() -> list[str]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("templates/*"):
        if not path.is_dir():
            continue
        files.extend(path.rglob("*.html"))
    return [p.read_text(encoding="utf-8") for p in sorted(set(files))]


def test_corpus_formats_under_budget() -> None:
    sources = _discover_sources()
    assert sources, "expected to discover at least one template"

    # Warm up: avoids first-run import/jit overhead skewing the timing.
    for src in sources:
        try:
            format_source(src)
        except (TokenizeError, ParseError):
            pass

    start = time.perf_counter()
    for src in sources:
        try:
            format_source(src)
        except (TokenizeError, ParseError):
            pass
    elapsed = time.perf_counter() - start

    assert elapsed < CORPUS_BUDGET_SECONDS, (
        f"formatter took {elapsed * 1000:.0f}ms across {len(sources)} templates "
        f"(budget {CORPUS_BUDGET_SECONDS * 1000:.0f}ms)"
    )
