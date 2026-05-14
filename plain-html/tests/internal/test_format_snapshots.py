"""Snapshot corpus for the formatter (tier-3 conformance).

Each subdirectory under `tests/fixtures/format/` is one case with two
files: `input.html` (raw source) and `expected.html` (canonical formatter
output). Tests assert `format_source(input) == expected` per case.

Add a new case by creating a subdirectory with both files. The case name
in test output is the directory name, so keep them short and topical
(`long_attributes/`, `brace_escape/`, etc.). When formatter behavior
changes intentionally, the `expected.html` update is a visible diff in
the PR — that's the audit trail.

Mirrors Prettier's `tests/format/html/` convention. Pattern is shared
with Black, ruff, dprint — well-trodden territory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plain.html.format import format_source

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "format"


def _discover_cases() -> list[Path]:
    return sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir())


_CASES = _discover_cases()


@pytest.mark.parametrize("case", _CASES, ids=lambda p: p.name)
def test_snapshot(case: Path) -> None:
    input_path = case / "input.html"
    expected_path = case / "expected.html"

    assert input_path.exists(), f"missing input.html in {case}"
    assert expected_path.exists(), f"missing expected.html in {case}"

    source = input_path.read_text(encoding="utf-8")
    expected = expected_path.read_text(encoding="utf-8")
    actual = format_source(source)

    assert actual == expected, (
        f"\n--- expected ({expected_path}) ---\n{expected}\n--- actual ---\n{actual}"
    )


def test_snapshot_corpus_is_nonempty() -> None:
    assert _CASES, "no snapshot cases discovered under tests/fixtures/format/"
