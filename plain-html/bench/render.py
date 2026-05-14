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
from plain.html.compiler import compile_path as _compile_path
from plain.html.compiler import compile_source as _compile_source
from plain.html.engine import render as _engine_render_path
from plain.html.engine import render_source as _render_source_real
from plain.html.frontmatter import split as split_frontmatter
from plain.html.parser import parse
from plain.html.tokenizer import tokenize


def _load_compiled(plain_source: str):
    """Compile a plain.html template to a Python module and return its render()."""
    import types

    src = _compile_source(plain_source, source_label="<bench>")
    mod = types.ModuleType(f"_bench_{abs(hash(plain_source))}")
    code = compile(src, "<bench>", "exec")
    exec(code, mod.__dict__)
    return mod.render


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
        {"items": [{"id": i, "name": f"Item {i}", "count": i * 7} for i in range(50)]},
        1_000,
    ),
    (
        "expression_heavy",
        "<div>" + "".join(f"<span>{{f_{i}}}</span>" for i in range(50)) + "</div>",
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
        {"users": [{"name": f"User {i}", "active": i % 2 == 0} for i in range(50)]},
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


class _Item:
    """Tiny attribute-only container for the include-in-loop case.

    Plain.html dotted access (`item.name`) goes through real attribute
    lookup; Jinja's `{{ item.name }}` does the same when given a class
    instance (it only falls back to `__getitem__` for dicts/Undefined).
    Using a class keeps the two engines symmetric.
    """

    __slots__ = ("email", "id", "name")

    def __init__(self, id: int, name: str, email: str) -> None:
        self.id = id
        self.name = name
        self.email = email


def _setup_extends(d: Path) -> tuple[Path, jinja2.Template]:
    """Layout-extends case. Parent layout with title + content slot;
    child page fills the slot with a heading + list.
    """
    d.mkdir(parents=True, exist_ok=True)

    (d / "layout.html").write_text(
        "---\n"
        "attrs:\n"
        "  title: str\n"
        "slots:\n"
        "  default: Markup\n"
        "---\n"
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><title>{title}</title></head>\n"
        "<body>\n"
        "  <header><h1>{title}</h1></header>\n"
        "  <main>{children}</main>\n"
        "  <footer>(c) 2026</footer>\n"
        "</body>\n"
        "</html>\n"
    )
    (d / "page.html").write_text(
        '<template :include="./layout" title={title}>\n'
        "  <p>Hello, {name}!</p>\n"
        "  <ul>\n"
        "    <li :for={item in items}>{item}</li>\n"
        "  </ul>\n"
        "</template>\n"
    )
    (d / "layout.j2").write_text(
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><title>{{ title }}</title></head>\n"
        "<body>\n"
        "  <header><h1>{{ title }}</h1></header>\n"
        "  <main>{% block content %}{% endblock %}</main>\n"
        "  <footer>(c) 2026</footer>\n"
        "</body>\n"
        "</html>\n"
    )
    (d / "page.j2").write_text(
        '{% extends "layout.j2" %}\n'
        "{% block content %}\n"
        "  <p>Hello, {{ name }}!</p>\n"
        "  <ul>\n"
        "    {% for item in items %}<li>{{ item }}</li>{% endfor %}\n"
        "  </ul>\n"
        "{% endblock %}\n"
    )

    jenv = jinja2.Environment(loader=jinja2.FileSystemLoader(str(d)), autoescape=False)
    return d / "page.html", jenv.get_template("page.j2")


def _setup_include_loop(d: Path) -> tuple[Path, jinja2.Template]:
    """Include-in-loop case. Per-row partial called 50 times per render."""
    d.mkdir(parents=True, exist_ok=True)

    (d / "row.html").write_text(
        "---\n"
        "attrs:\n"
        "  item: Any\n"
        "---\n"
        "<tr>"
        "<td>{item.id}</td>"
        "<td>{item.name}</td>"
        "<td>{item.email}</td>"
        "</tr>\n"
    )
    (d / "list.html").write_text(
        "<table>\n"
        '  <template :for={item in items} :include="./row" item={item} />\n'
        "</table>\n"
    )
    (d / "row.j2").write_text(
        "<tr>"
        "<td>{{ item.id }}</td>"
        "<td>{{ item.name }}</td>"
        "<td>{{ item.email }}</td>"
        "</tr>\n"
    )
    (d / "list.j2").write_text(
        "<table>\n"
        '  {% for item in items %}{% include "row.j2" %}{% endfor %}\n'
        "</table>\n"
    )

    jenv = jinja2.Environment(loader=jinja2.FileSystemLoader(str(d)), autoescape=False)
    return d / "list.html", jenv.get_template("list.j2")


FILE_CASES = [
    (
        "extends_layout",
        _setup_extends,
        {"title": "Page", "name": "Dave", "items": list(range(10))},
        2_000,
    ),
    (
        "include_in_loop",
        _setup_include_loop,
        {"items": [_Item(i, f"User {i}", f"u{i}@example.com") for i in range(50)]},
        1_000,
    ),
]


def _run_file_cases() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for label, setup, ctx, iters in FILE_CASES:
            plain_entry, jinja_tpl = setup(root / label)

            # Pre-compile both engines once; we measure steady-state render cost.
            compiled_render = _compile_path(plain_entry)

            # Match plain.html's call convention: positional path + ctx dict
            # for the interpreter, kwargs for the compiled function.
            i_stats = time_callable(
                lambda p=plain_entry, c=ctx: _engine_render_path(p, c), iters
            )
            c_stats = time_callable(lambda r=compiled_render, c=ctx: r(**c), iters)
            j_stats = time_callable(lambda t=jinja_tpl, c=ctx: t.render(**c), iters)

            ratio = (
                c_stats["median_us"] / j_stats["median_us"]
                if j_stats["median_us"] > 0
                else 0
            )
            print(
                f"{label:<22} "
                f"{i_stats['median_us']:>8.1f}us "
                f"{c_stats['median_us']:>8.1f}us "
                f"{j_stats['median_us']:>8.1f}us "
                f"{ratio:>9.1f}x"
            )


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

    columns = ["case", "interp", "+tree", "+tree+expr", "compiled", "jinja", "vs jinja"]
    print(
        f"{columns[0]:<22} {columns[1]:>10} {columns[2]:>10} "
        f"{columns[3]:>12} {columns[4]:>10} {columns[5]:>10} {columns[6]:>10}"
    )
    print("-" * 90)

    for label, p_src, j_src, ctx, iters in CASES:
        # 1) plain.html current path — re-parses every call.
        _restore_eval()
        _cached_parse.cache_clear()
        baseline = time_callable(lambda: render_source(p_src, ctx), iters)

        # 2) + tree cache
        _restore_eval()
        _cached_parse.cache_clear()
        tree_cached = time_callable(lambda: render_with_tree_cache(p_src, ctx), iters)

        # 3) + tree cache + compiled-expression cache
        _install_expression_cache()
        _cached_parse.cache_clear()
        both_cached = time_callable(lambda: render_with_tree_cache(p_src, ctx), iters)
        _restore_eval()

        # 4) compiled (Phase 5b) — AOT-emitted Python with inlined expressions.
        compiled_render = _load_compiled(p_src)
        compiled = time_callable(lambda: compiled_render(**ctx), iters)

        # 5) Jinja — compile once, then call .render(**ctx).
        jt = jenv.from_string(j_src)
        j = time_callable(lambda: jt.render(**ctx), iters)

        ratio = compiled["median_us"] / j["median_us"] if j["median_us"] > 0 else 0
        print(
            f"{label:<22} "
            f"{baseline['median_us']:>8.1f}us "
            f"{tree_cached['median_us']:>8.1f}us "
            f"{both_cached['median_us']:>10.1f}us "
            f"{compiled['median_us']:>8.1f}us "
            f"{j['median_us']:>8.1f}us "
            f"{ratio:>9.1f}x"
        )

    # File-based cases that exercise the include/slot machinery — closest
    # to the templates real apps ship: a layout shared by every page, plus
    # per-row partials called inside a loop.
    print()
    print("File-based templates (extends layout + include in loop):")
    columns2 = ["case", "interp", "compiled", "jinja", "vs jinja"]
    print(
        f"{columns2[0]:<22} {columns2[1]:>10} {columns2[2]:>10} "
        f"{columns2[3]:>10} {columns2[4]:>10}"
    )
    print("-" * 70)
    _run_file_cases()

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
