"""Perf regression gate for the compiler render path.

Phase 5's plan calls for a CI-runnable check that the compiled
`render()` for each bench case stays under a generous absolute floor.
We're not asserting "≤ 2× Jinja" here — Jinja isn't a dependency of
this package any more — just that no single bench case takes more
than the budget per render, warm.

If this trips, the gap is real. Look at `bench/render.py` for the
human-inspection numbers (compares against Jinja) and start from
whatever case regressed.

The cases come from `_perf_fixtures.py`, which mirrors the inline
CASES in `bench/render.py`. Keep both in sync.
"""

from __future__ import annotations

import statistics
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest

from plain.html.compiler import CompileSession

# `tests/internal/` isn't a package — no __init__.py — so a relative
# import doesn't work. Add the directory to sys.path so the shared
# fixtures module loads as a plain module.
sys.path.insert(0, str(Path(__file__).parent))
from _perf_fixtures import PERF_CASES  # noqa: E402

# 25 ms per warm render. Bench numbers as of writing are all sub-millisecond;
# the budget is loose enough to absorb CI machine variance (typically 3-5×
# slower than a developer laptop) while still catching a 25×+ regression.
# Each bench case completes in <5 ms warm on a developer machine, so the
# budget is a 5× safety margin on the slowest expected CI runtime.
RENDER_BUDGET_SECONDS = 0.025

# Iteration count per case for the timing loop. Keep this small enough that
# the whole suite stays fast (we don't need bench-level precision — we just
# need the median to be a stable signal).
ITERS = 200


def _load_compiled(plain_source: str) -> Any:
    """Compile a plain.html source string and return its render fn.

    Mirrors the helper in `bench/render.py` exactly so the timed code
    path is identical to the human-inspection bench.
    """
    src = CompileSession().compile_string(plain_source, label="<perf>")
    mod = types.ModuleType(f"_perf_{abs(hash(plain_source))}")
    code = compile(src, "<perf>", "exec")
    exec(code, mod.__dict__)
    return mod.render


@pytest.mark.parametrize(
    ("label", "source", "context"),
    PERF_CASES,
    ids=[case[0] for case in PERF_CASES],
)
def test_compiled_render_under_budget(label: str, source: str, context: dict) -> None:
    """Median warm render time per case stays under the absolute floor."""
    render_fn = _load_compiled(source)

    # Warm up: first call pays any lazy-import cost in the runtime helpers.
    render_fn(**context)

    samples = []
    for _ in range(ITERS):
        start = time.perf_counter()
        render_fn(**context)
        samples.append(time.perf_counter() - start)
    median = statistics.median(samples)

    assert median < RENDER_BUDGET_SECONDS, (
        f"compiled render for {label!r} median {median * 1000:.2f}ms "
        f"exceeds budget {RENDER_BUDGET_SECONDS * 1000:.0f}ms — investigate "
        f"before merging; see bench/render.py for human-inspection numbers"
    )
