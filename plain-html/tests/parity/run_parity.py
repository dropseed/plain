"""Phase 0 parity harness.

Renders each paired fixture under both Jinja and `plain.html`, captures the
raw and whitespace-normalized outputs, and writes a unified diff. Used to
validate the spec end-to-end on real-shape templates before broader migration
work begins.

Run from the repo root:

    uv run python plain-html/tests/parity/run_parity.py

Outputs land in `plain-html/tests/parity/results/` (gitignored at the parent
level but committed as the diff artifact for this branch).
"""

from __future__ import annotations

import difflib
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import jinja2

import plain.html

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
RESULTS = HERE / "results"


@dataclass
class ParityResult:
    fixture: str
    scenario: str
    jinja_output: str
    plain_output: str
    raw_diff: str
    normalized_diff: str

    @property
    def raw_match(self) -> bool:
        return not self.raw_diff

    @property
    def normalized_match(self) -> bool:
        return not self.normalized_diff


def _load_context_module(path: Path):
    name = f"_parity_fixture_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _normalize(html: str) -> str:
    """Collapse inter-tag whitespace and trim. Mirrors what the eventual harness
    will do when asserting parity — small whitespace differences that don't
    change rendered semantics are tolerated, real content differences aren't.
    """
    # Collapse runs of whitespace between tags to a single newline.
    html = re.sub(r">\s+<", ">\n<", html)
    # Collapse other internal whitespace runs.
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()


def _render_jinja(template_path: Path, context: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path.parent),
        autoescape=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(context)


def _render_plain(template_path: Path, context: dict) -> str:
    return plain.html.render(template_path, context)


def _diff(a: str, b: str, *, label_a: str, label_b: str) -> str:
    if a == b:
        return ""
    diff = difflib.unified_diff(
        a.splitlines(keepends=True),
        b.splitlines(keepends=True),
        fromfile=label_a,
        tofile=label_b,
        lineterm="",
    )
    return "".join(diff)


def run() -> list[ParityResult]:
    results: list[ParityResult] = []
    RESULTS.mkdir(exist_ok=True)
    for ctx_path in sorted(FIXTURES.glob("*.py")):
        stem = ctx_path.stem
        jinja_path = FIXTURES / f"{stem}.html"
        plain_path = FIXTURES / f"{stem}.plain"
        if not jinja_path.exists() or not plain_path.exists():
            continue
        ctx_module = _load_context_module(ctx_path)
        scenarios = getattr(ctx_module, "SCENARIOS", {"default": lambda: {}})
        for scenario_name, scenario_factory in scenarios.items():
            ctx = scenario_factory()
            jinja_out = _render_jinja(jinja_path, ctx)
            plain_out = _render_plain(plain_path, ctx)
            raw_diff = _diff(
                jinja_out,
                plain_out,
                label_a=f"jinja:{stem}.html [{scenario_name}]",
                label_b=f"plain:{stem}.plain [{scenario_name}]",
            )
            normalized_diff = _diff(
                _normalize(jinja_out),
                _normalize(plain_out),
                label_a=f"jinja:{stem}.html [{scenario_name}] (normalized)",
                label_b=f"plain:{stem}.plain [{scenario_name}] (normalized)",
            )
            result = ParityResult(
                fixture=stem,
                scenario=scenario_name,
                jinja_output=jinja_out,
                plain_output=plain_out,
                raw_diff=raw_diff,
                normalized_diff=normalized_diff,
            )
            results.append(result)
            _write_artifacts(result)
    return results


def _write_artifacts(result: ParityResult) -> None:
    prefix = RESULTS / f"{result.fixture}__{result.scenario}"
    (prefix.with_suffix(".jinja.out")).write_text(result.jinja_output)
    (prefix.with_suffix(".plain.out")).write_text(result.plain_output)
    raw_path = prefix.with_suffix(".raw.diff")
    if result.raw_diff:
        raw_path.write_text(result.raw_diff)
    elif raw_path.exists():
        raw_path.unlink()
    norm_path = prefix.with_suffix(".normalized.diff")
    if result.normalized_diff:
        norm_path.write_text(result.normalized_diff)
    elif norm_path.exists():
        norm_path.unlink()


def _print_summary(results: list[ParityResult]) -> int:
    labels = [f"{r.fixture}/{r.scenario}" for r in results]
    width = max((len(label) for label in labels), default=20)
    width = max(width, len("fixture/scenario"))
    fail = 0
    print(f"{'fixture/scenario':<{width}}  raw    normalized")
    print("-" * (width + 18))
    for r, label in zip(results, labels, strict=True):
        raw_status = "match" if r.raw_match else "DIFF"
        norm_status = "match" if r.normalized_match else "DIFF"
        if not r.normalized_match:
            fail += 1
        print(f"{label:<{width}}  {raw_status:<5}  {norm_status}")
    print()
    print(f"{len(results)} comparison(s), {fail} normalized-diff failure(s).")
    print(f"Artifacts: {RESULTS}")
    return fail


if __name__ == "__main__":
    results = run()
    fail = _print_summary(results)
    sys.exit(1 if fail else 0)
