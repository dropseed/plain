"""End-to-end `plain html check --typecheck` behavior tests.

Drives the full pipeline against ty, which must be installed locally
(pinned in `plain.html`'s dev dependencies). If ty isn't available the
test is skipped — useful when contributors run a subset locally.
"""

from __future__ import annotations

import shutil

import pytest

from plain.html.typecheck import check_source
from plain.html.typecheck.backends import TyBackend

pytestmark = pytest.mark.skipif(
    shutil.which("ty") is None,
    reason="ty is not installed; install with `uv tool install ty`",
)


def _check(source: str, *, cache_root):
    return check_source(
        source,
        backend=TyBackend(),
        cache_root=cache_root,
        use_cache=False,
    )


def test_well_typed_template_has_no_errors(tmp_path):
    source = """---
attrs:
  name: str
  count: int = 0
---
<p>Hello, {{ name }}! Count: {{ count }}</p>
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors == []


def test_wrong_typed_expression_is_caught(tmp_path):
    source = """---
attrs:
  name: str
---
<p>{{ name + 5 }}</p>
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors, "Expected ty to flag str + int"
    [err] = errors
    assert err.severity == "error"
    # Should point at the template line, not the synth file line.
    assert err.line == 5
    assert err.kind == "expr"


def test_attribute_position_expression_typed(tmp_path):
    source = """---
attrs:
  count: int
---
<button disabled={{ count + "x" }}>x</button>
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors
    assert any("Operator" in e.message or "unsupported" in e.code for e in errors)


def test_for_loop_binds_iteration_variable(tmp_path):
    source = """---
attrs:
  items: list[int]
---
<ul>
  {% for item in items %}<li>{{ item + 1 }}</li>{% endfor %}
</ul>
"""
    errors = _check(source, cache_root=tmp_path)
    # item is `int`, +1 is fine — no errors expected.
    assert errors == [], [e.format() for e in errors]


def test_for_loop_variable_typing_caught(tmp_path):
    source = """---
attrs:
  items: list[int]
---
<ul>
  {% for item in items %}<li>{{ item + "x" }}</li>{% endfor %}
</ul>
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors, "Expected int + str to be flagged inside {% for %} body"


def test_if_block_expression_typed(tmp_path):
    source = """---
attrs:
  count: int
---
{% if count.foo %}<span>x</span>{% endif %}
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors
    assert errors[0].kind == "if"


def test_cache_round_trip(tmp_path):
    """The cache returns the same diagnostics on the second pass."""
    source = """---
attrs:
  name: str
---
<p>{{ name + 5 }}</p>
"""
    backend = TyBackend()
    # First pass — populate cache.
    first = check_source(source, backend=backend, cache_root=tmp_path, use_cache=True)
    second = check_source(source, backend=backend, cache_root=tmp_path, use_cache=True)
    assert [e.format() for e in first] == [e.format() for e in second]


def test_frontmatter_error_surfaces_at_top_of_file(tmp_path):
    source = """---
attrs:
  bad-name: str
---
<p>hi</p>
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors
    assert errors[0].code == "frontmatter"
    assert errors[0].line == 1


def test_component_call_site_wrong_attr_type_caught(tmp_path):
    """A component tag passing a mistyped attr is flagged against the
    imported component's declared `attrs:` signature."""
    from plain.html.typecheck import check_path

    (tmp_path / "Card.html").write_text(
        "---\nattrs:\n  count: int\n---\n<p>{{ count }}</p>\n"
    )
    page = tmp_path / "page.html"
    page.write_text('---\ncomponents:\n  - ./Card\n---\n<Card count={{ "nope" }} />\n')
    errors = check_path(page, backend=TyBackend(), use_cache=False, cache_root=tmp_path)
    assert errors, "expected ty to flag str passed where int declared"
    assert errors[0].kind == "component"


def test_component_call_site_well_typed_has_no_errors(tmp_path):
    from plain.html.typecheck import check_path

    (tmp_path / "Card.html").write_text(
        "---\nattrs:\n  count: int\n---\n<p>{{ count }}</p>\n"
    )
    page = tmp_path / "page.html"
    page.write_text("---\ncomponents:\n  - ./Card\n---\n<Card count={{ 5 }} />\n")
    errors = check_path(page, backend=TyBackend(), use_cache=False, cache_root=tmp_path)
    assert errors == [], [e.format() for e in errors]


def test_editing_a_component_invalidates_parent_cache(tmp_path):
    """Editing a component's `attrs:` must invalidate a parent template's
    cached typecheck result — the component source is folded into the
    cache key."""
    from plain.html.typecheck import check_path

    card = tmp_path / "Card.html"
    card.write_text("---\nattrs:\n  count: int\n---\n<p>{{ count }}</p>\n")
    page = tmp_path / "page.html"
    page.write_text("---\ncomponents:\n  - ./Card\n---\n<Card count={{ 5 }} />\n")

    backend = TyBackend()
    # First pass — `count={5}` is fine against `count: int`. Populates cache.
    first = check_path(page, backend=backend, use_cache=True, cache_root=tmp_path)
    assert first == [], [e.format() for e in first]

    # Edit the component so `count` is now `str` — the same call site
    # (`count={5}`) is now mistyped. A stale cache would still report clean.
    card.write_text("---\nattrs:\n  count: str\n---\n<p>{{ count }}</p>\n")
    second = check_path(page, backend=backend, use_cache=True, cache_root=tmp_path)
    assert second, "expected cache invalidation to surface the new type error"


def test_cache_key_changes_with_component_source():
    """`cache_key` folds component file contents into the key."""
    from plain.html.typecheck import cache
    from plain.html.typecheck.declarations import parse as parse_declarations

    declarations = parse_declarations({"components": ["./Card"]})

    def key(component_source: str) -> str:
        return cache.cache_key(
            source="<Card />\n",
            declarations=declarations,
            backend_name="ty",
            backend_version="0.0.0",
            component_sources={"Card": component_source},
        )

    assert key("attrs:\n  x: int\n") != key("attrs:\n  x: str\n")


def test_slot_param_typed_as_safe_string(tmp_path):
    source = """---
slots:
  header: optional
---
<header>{{ header }}</header>
"""
    errors = _check(source, cache_root=tmp_path)
    assert errors == []
