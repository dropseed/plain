"""Plain.html vs Jinja render benchmark.

Measures the steady-state per-render cost of the AOT compiler against
an equivalent Jinja2 template. Both engines compile once outside the
timing loop — production-realistic, where templates are warm.

Run from the example app so the plain.html runtime is configured and
jinja2 is available on the bench's PATH:

    cd example && uv run --with jinja2 plain run ../plain-html/bench/render.py

Numbers are not asserted as a regression gate — that's
`tests/internal/test_format_performance.py`. This is for ad-hoc
measurement when evaluating perf changes to the compiler.
"""

from __future__ import annotations

import statistics
import tempfile
import time
import types
from pathlib import Path
from typing import Any

import jinja2

from plain.html.compiler import CompileSession, get_or_compile


def _load_compiled(plain_source: str) -> Any:
    """Compile a plain.html source string and return its render fn."""
    src = CompileSession().compile_string(plain_source, label="<bench>")
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


class _Item:
    """Tiny attribute-only container for the include-in-loop case.

    Plain.html dotted access (`item.name`) goes through real attribute
    lookup; Jinja's `{{ item.name }}` does the same when given a class
    instance (only falls back to `__getitem__` for dicts). Using a
    class keeps the two engines symmetric.
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


def time_callable(fn: Any, iters: int) -> dict[str, float]:
    fn()  # warm-up
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


def _run_inline_cases() -> None:
    jenv = jinja2.Environment(autoescape=False, cache_size=400)
    columns = ["case", "compiled", "jinja", "vs jinja"]
    print(f"{columns[0]:<22} {columns[1]:>10} {columns[2]:>10} {columns[3]:>10}")
    print("-" * 60)
    for label, p_src, j_src, ctx, iters in CASES:
        compiled_render = _load_compiled(p_src)
        c = time_callable(lambda: compiled_render(**ctx), iters)
        jt = jenv.from_string(j_src)
        j = time_callable(lambda: jt.render(**ctx), iters)
        ratio = c["median_us"] / j["median_us"] if j["median_us"] > 0 else 0
        print(
            f"{label:<22} "
            f"{c['median_us']:>8.1f}us "
            f"{j['median_us']:>8.1f}us "
            f"{ratio:>9.1f}x"
        )


def _run_file_cases() -> None:
    columns = ["case", "compiled", "jinja", "vs jinja"]
    print(f"{columns[0]:<22} {columns[1]:>10} {columns[2]:>10} {columns[3]:>10}")
    print("-" * 60)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for label, setup, ctx, iters in FILE_CASES:
            plain_entry, jinja_tpl = setup(root / label)
            compiled_render = get_or_compile(plain_entry)
            c = time_callable(lambda: compiled_render(**ctx), iters)
            j = time_callable(lambda: jinja_tpl.render(**ctx), iters)
            ratio = c["median_us"] / j["median_us"] if j["median_us"] > 0 else 0
            print(
                f"{label:<22} "
                f"{c['median_us']:>8.1f}us "
                f"{j['median_us']:>8.1f}us "
                f"{ratio:>9.1f}x"
            )


def _run_corpus() -> None:
    """How long does it take to compile every template in the repo?"""
    files: list[Path] = []
    for d in REPO.rglob("html/*"):
        if d.is_dir():
            files.extend(d.rglob("*.html"))
    files = sorted(set(files))

    # warm
    for f in files:
        try:
            get_or_compile(f)
        except Exception:
            pass

    t0 = time.perf_counter()
    ok = err = 0
    for f in files:
        try:
            get_or_compile(f)
            ok += 1
        except Exception:
            err += 1
    elapsed = (time.perf_counter() - t0) * 1000
    print(
        f"  {len(files)} templates, {ok} compiled, {err} errored: "
        f"{elapsed:.1f}ms total, {elapsed / max(ok, 1):.2f}ms avg per template"
    )


def main() -> None:
    print("Inline templates (compiled once, then timed in a loop):")
    _run_inline_cases()
    print()
    print("File-based templates (extends layout + include in loop):")
    _run_file_cases()
    print()
    print("Compile corpus (every template in the repo, warm process cache):")
    _run_corpus()


if __name__ == "__main__":
    main()
