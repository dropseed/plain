"""Plain.html vs Jinja render benchmark.

Measures the cost of `render_source()` on representative templates from
the repo, side-by-side with an equivalent Jinja2 template. Jinja
compiles + caches templates by default; plain.html currently re-parses
on every render. Also sketches what tree-cache and compiled-expression
caches would buy, so the gap to Jinja parity is quantified.

Run from the example app so the plain.html runtime is configured and
jinja2 is available on the bench's PATH:

    cd example && uv run --with jinja2 plain run ../plain-html/bench/render.py

Numbers are intentionally not asserted as a regression gate — that
lives in `tests/internal/test_format_performance.py`. This script is
for ad-hoc measurement when evaluating perf changes to the engine.
"""

from __future__ import annotations

import functools
import statistics
import time
from pathlib import Path
from typing import Any

import jinja2

from plain.html import engine as html_engine
from plain.html.engine import render_source as _render_source_real
from plain.html.frontmatter import split as split_frontmatter
from plain.html.parser import parse
from plain.html.tokenizer import tokenize


def _find_repo_root() -> Path:
    # `plain run` exec()s this script without setting __file__, so walk
    # up from CWD looking for the implementation-plan marker instead.
    here = Path.cwd().resolve()
    for parent in [here, *here.parents]:
        if (parent / "plain-html-implementation-plan.md").exists():
            return parent
    raise RuntimeError(
        "Could not locate repo root — run from inside the plain checkout."
    )


REPO = _find_repo_root()

# Each case: (label, plain_source, jinja_source, context, iters).
# The two source forms must render to functionally equivalent output so
# the timings are apples to apples.
CASES: list[tuple[str, str, str, dict, int]] = [
    (
        "tiny",
        "<p>Hello, {name}!</p>",
        "<p>Hello, {{ name }}!</p>",
        {"name": "Dave"},
        10_000,
    ),
    (
        "medium_list",
        """<ul>
            <li :for={item in items}>
                <a href="/i/{item['id']}">{item['name']}</a>
                <span class="meta">{item['count']} views</span>
            </li>
        </ul>""",
        """<ul>
            {% for item in items %}
            <li>
                <a href="/i/{{ item['id'] }}">{{ item['name'] }}</a>
                <span class="meta">{{ item['count'] }} views</span>
            </li>
            {% endfor %}
        </ul>""",
        {
            "items": [
                {"id": i, "name": f"Item {i}", "count": i * 7}
                for i in range(50)
            ]
        },
        1_000,
    ),
    (
        "expression_heavy",
        "<div>"
        + "".join(f"<span>{{f_{i}}}</span>" for i in range(50))
        + "</div>",
        "<div>"
        + "".join(f"<span>{{{{ f_{i} }}}}</span>" for i in range(50))
        + "</div>",
        {f"f_{i}": f"value_{i}" for i in range(50)},
        2_000,
    ),
    (
        "nested_loops",
        """<table>
            <tr :for={row in rows}>
                <td :for={cell in row}>{cell}</td>
            </tr>
        </table>""",
        """<table>
            {% for row in rows %}<tr>
                {% for cell in row %}<td>{{ cell }}</td>{% endfor %}
            </tr>{% endfor %}
        </table>""",
        {"rows": [[f"r{r}c{c}" for c in range(8)] for r in range(20)]},
        1_000,
    ),
    (
        "conditionals",
        """<div>
            <p :for={u in users}>
                <strong :if={u['active']}>{u['name']}</strong>
                <span :if={not u['active']}>(inactive: {u['name']})</span>
            </p>
        </div>""",
        """<div>
            {% for u in users %}<p>
                {% if u['active'] %}<strong>{{ u['name'] }}</strong>{% endif %}
                {% if not u['active'] %}<span>(inactive: {{ u['name'] }})</span>{% endif %}
            </p>{% endfor %}
        </div>""",
        {
            "users": [
                {"name": f"User {i}", "active": i % 2 == 0}
                for i in range(50)
            ]
        },
        1_000,
    ),
]


def render_source(source: str, context: dict | None = None) -> str:
    """Pass-through that respects the current monkey-patches below."""
    return _render_source_real(source, context)


@functools.lru_cache(maxsize=512)
def _cached_parse(body: str) -> Any:
    return parse(tokenize(body))


def render_with_tree_cache(source: str, context: dict | None = None) -> str:
    """Cache the parsed tree per body string. Skip tokenize+parse on
    subsequent renders of the same template source.
    """
    fmdict, body = split_frontmatter(source)
    tree = _cached_parse(body)
    ctx = dict(context or {})
    for attr_name in fmdict.get("attrs", {}) or {}:
        ctx.setdefault(attr_name, None)
    scope = html_engine._build_scope(fmdict, ctx, None)
    out: list[str] = []
    for node in tree:
        html_engine._render_node(node, scope, None, ctx, out)
    return "".join(out)


_ORIGINAL_EVAL = html_engine._eval


def _install_expression_cache() -> None:
    """Patch the engine's `_eval` to pre-compile expressions and cache
    the code objects. The next call to `_eval(code_str, scope)` looks
    up the cached code object instead of re-parsing the source.
    """
    cache: dict[str, Any] = {}

    def fast_eval(code: str, scope: dict) -> Any:
        co = cache.get(code)
        if co is None:
            co = compile(code, "<template-expr>", "eval")
            cache[code] = co
        try:
            return eval(co, scope)
        except Exception as e:
            from plain.html.engine import RenderError

            raise RenderError(f"Error evaluating {code!r}: {e}") from e

    html_engine._eval = fast_eval  # type: ignore[assignment]


def _restore_eval() -> None:
    html_engine._eval = _ORIGINAL_EVAL  # type: ignore[assignment]


def time_callable(fn, iters: int) -> dict[str, float]:
    # Warm up so import / first-call cost doesn't skew the timing.
    fn()
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return {
        "median_us": samples[len(samples) // 2] * 1_000_000,
        "p99_us": samples[int(len(samples) * 0.99)] * 1_000_000,
        "mean_us": statistics.mean(samples) * 1_000_000,
        "total_ms": sum(samples) * 1000,
    }


def main() -> None:
    # Pre-compile the Jinja templates outside the timing loop — that's
    # what production would do: Jinja's `env.get_template(...)` compiles
    # once and caches the function. We measure the steady-state per-call
    # cost, which is what request handling sees.
    jenv = jinja2.Environment(autoescape=False, cache_size=400)

    columns = ["case", "plain", "+tree", "+tree+expr", "jinja", "vs jinja"]
    print(
        f"{columns[0]:<22} {columns[1]:>10} {columns[2]:>10} "
        f"{columns[3]:>12} {columns[4]:>10} {columns[5]:>10}"
    )
    print("-" * 80)

    for label, p_src, j_src, ctx, iters in CASES:
        # 1) plain.html current path — re-parses every call.
        _restore_eval()
        _cached_parse.cache_clear()
        baseline = time_callable(lambda: render_source(p_src, ctx), iters)

        # 2) + tree cache
        _restore_eval()
        _cached_parse.cache_clear()
        tree_cached = time_callable(
            lambda: render_with_tree_cache(p_src, ctx), iters
        )

        # 3) + tree cache + compiled-expression cache
        _install_expression_cache()
        _cached_parse.cache_clear()
        both_cached = time_callable(
            lambda: render_with_tree_cache(p_src, ctx), iters
        )
        _restore_eval()

        # 4) Jinja — compile once, then call .render(**ctx).
        jt = jenv.from_string(j_src)
        j = time_callable(lambda: jt.render(**ctx), iters)

        ratio = both_cached["median_us"] / j["median_us"] if j["median_us"] > 0 else 0
        print(
            f"{label:<22} "
            f"{baseline['median_us']:>8.1f}us "
            f"{tree_cached['median_us']:>8.1f}us "
            f"{both_cached['median_us']:>10.1f}us "
            f"{j['median_us']:>8.1f}us "
            f"{ratio:>9.1f}x"
        )

    # Aggregate corpus render — single render of every repo template
    # with empty context. Errors swallowed.
    print()
    print("Corpus render (every template once, empty ctx, errors swallowed):")
    files: list[Path] = []
    for d in REPO.rglob("html/*"):
        if d.is_dir():
            files.extend(d.rglob("*.html"))
    files = sorted(set(files))
    sources = [(f, f.read_text()) for f in files]

    # warm
    for f, src in sources:
        try:
            render_source(src, {})
        except Exception:
            pass

    t0 = time.perf_counter()
    ok = err = 0
    for f, src in sources:
        try:
            render_source(src, {})
            ok += 1
        except Exception:
            err += 1
    elapsed = (time.perf_counter() - t0) * 1000
    print(
        f"  {len(sources)} templates, {ok} rendered ok, {err} errored: "
        f"{elapsed:.1f}ms total, {elapsed / max(ok, 1):.2f}ms avg per template"
    )


if __name__ == "__main__":
    main()
