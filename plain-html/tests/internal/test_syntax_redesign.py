"""Tests for the block-syntax control flow.

Covers the `{% %}`-block engine:
  - `{% for %}` loops, including comprehension-clause filters
  - `{% if %}` / `{% elif %}` / `{% else %}` chains and their errors
  - `components:` frontmatter + PascalCase component tags
  - `{% slot %}` blocks routing content into named slots
  - HTML-aware enforcement: straddle and start-tag-block rejection
  - the removal of the old `:if`/`:for`/`:slot` directive sugar

These exercise behavior at the parse + compile + render layer, the same
style as `test_compiler.py`.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from plain.html.compiler import CompileError, CompileSession
from plain.html.components import ComponentsError, parse_components
from plain.html.parser import ParseError
from plain.html.tokenizer import TokenizeError


def _compile_string(source: str, *, label: str = "<test>") -> str:
    return CompileSession().compile_string(source, label=label)


def _load(source: str, *, label: str = "<test>"):
    src = _compile_string(source, label=label)
    mod = types.ModuleType(f"_plain_html_test_{abs(hash(source))}")
    mod.__file__ = label
    exec(compile(src, label, "exec"), mod.__dict__)
    return mod.render


def _compile_path(path: Path):
    return CompileSession().compile_path(path)


def _write_templates(tmp_path: Path, templates: dict[str, str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, src in templates.items():
        p = tmp_path / f"{name}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
        out[name] = p
    return out


# --- {% for %} loops ---------------------------------------------------------


def test_for_basic():
    out = _load("{% for x in items %}<li>{{ x }}</li>{% endfor %}")(items=[1, 2, 3])
    assert out == "<li>1</li><li>2</li><li>3</li>"


def test_for_tuple_unpack():
    src = "{% for (k, v) in pairs %}<i>{{ k }}{{ v }}</i>{% endfor %}"
    out = _load(src)(pairs=[("a", 1), ("b", 2)])
    assert out == "<i>a1</i><i>b2</i>"


def test_for_with_no_wrapper_element():
    out = _load("{% for x in items %}{{ x }}{% endfor %}")(items=[0, 1, 0, 2])
    assert out == "0102"


# --- {% for %} comprehension-clause filter -----------------------------------


def test_for_filter_basic():
    out = _load("{% for x in items if x > 2 %}<li>{{ x }}</li>{% endfor %}")(
        items=[1, 2, 3, 4]
    )
    assert out == "<li>3</li><li>4</li>"


def test_for_filter_with_tuple_target():
    src = (
        "{% for (i, x) in enumerate(items) if i % 2 == 0 %}<li>{{ x }}</li>{% endfor %}"
    )
    out = _load(src)(items=["a", "b", "c", "d"])
    assert out == "<li>a</li><li>c</li>"


def test_for_filter_multiple_ifs():
    src = "{% for x in items if x > 1 if x < 4 %}<li>{{ x }}</li>{% endfor %}"
    out = _load(src)(items=[0, 1, 2, 3, 4, 5])
    assert out == "<li>2</li><li>3</li>"


def test_for_nested_for_clause_rejected():
    with pytest.raises(ParseError, match="one `for` clause"):
        _compile_string("{% for x in xs for y in ys %}{{ x }}{% endfor %}")


def test_for_missing_in_separator_rejected():
    with pytest.raises(ParseError, match="in"):
        _compile_string("{% for x xs %}{{ x }}{% endfor %}")


def test_for_requires_argument():
    with pytest.raises(ParseError, match="`{% for %}` requires an argument"):
        _compile_string("{% for %}x{% endfor %}")


def test_unclosed_for_rejected():
    with pytest.raises(ParseError, match="Unclosed `{% for %}`"):
        _compile_string("{% for x in xs %}<li>{{ x }}</li>")


# --- {% if %} / {% elif %} / {% else %} chains -------------------------------


def test_if_elif_else_first_branch():
    render = _load(
        "{% if n == 1 %}<p>one</p>{% elif n == 2 %}<p>two</p>{% else %}<p>many</p>{% endif %}"
    )
    assert render(n=1) == "<p>one</p>"


def test_if_elif_else_middle_branch():
    render = _load(
        "{% if n == 1 %}<p>one</p>{% elif n == 2 %}<p>two</p>{% else %}<p>many</p>{% endif %}"
    )
    assert render(n=2) == "<p>two</p>"


def test_if_elif_else_else_branch():
    render = _load(
        "{% if n == 1 %}<p>one</p>{% elif n == 2 %}<p>two</p>{% else %}<p>many</p>{% endif %}"
    )
    assert render(n=9) == "<p>many</p>"


def test_lone_if_still_works():
    render = _load("{% if show %}<p>hi</p>{% endif %}")
    assert render(show=True) == "<p>hi</p>"
    assert render(show=False) == ""


def test_if_else_without_elif():
    render = _load("{% if ok %}<p>yes</p>{% else %}<p>no</p>{% endif %}")
    assert render(ok=True) == "<p>yes</p>"
    assert render(ok=False) == "<p>no</p>"


def test_branches_vary_the_whole_element():
    # The supported way to "straddle" — two balanced branches, each a
    # complete element.
    render = _load("{% if big %}<h1>T</h1>{% else %}<h2>T</h2>{% endif %}")
    assert render(big=True) == "<h1>T</h1>"
    assert render(big=False) == "<h2>T</h2>"


def test_elif_with_for_loop_in_branch():
    src = (
        "{% if mode == 'a' %}<p>A</p>"
        "{% elif mode == 'b' %}<ul>{% for x in xs %}<li>{{ x }}</li>{% endfor %}</ul>"
        "{% endif %}"
    )
    render = _load(src)
    assert render(mode="a", xs=[]) == "<p>A</p>"
    assert render(mode="b", xs=[1, 2]) == "<ul><li>1</li><li>2</li></ul>"


def test_orphan_elif_rejected():
    with pytest.raises(ParseError, match="elif"):
        _compile_string("<p>x</p>{% elif y %}z{% endif %}")


def test_orphan_else_rejected():
    with pytest.raises(ParseError, match="else"):
        _compile_string("<p>x</p>{% else %}z{% endif %}")


def test_elif_after_else_rejected():
    with pytest.raises(ParseError, match="elif"):
        _compile_string("{% if a %}1{% else %}2{% elif b %}3{% endif %}")


def test_two_else_rejected():
    with pytest.raises(ParseError, match="else"):
        _compile_string("{% if a %}1{% else %}2{% else %}3{% endif %}")


def test_if_requires_argument():
    with pytest.raises(ParseError, match="`{% if %}` requires an argument"):
        _compile_string("{% if %}x{% endif %}")


def test_elif_requires_argument():
    with pytest.raises(ParseError, match="`{% elif %}` requires an argument"):
        _compile_string("{% if a %}1{% elif %}2{% endif %}")


def test_else_takes_no_argument():
    with pytest.raises(ParseError, match="`{% else %}` takes no arguments"):
        _compile_string("{% if a %}1{% else x %}2{% endif %}")


def test_unclosed_if_rejected():
    with pytest.raises(ParseError, match="Unclosed `{% if %}`"):
        _compile_string("{% if a %}<p>x</p>")


def test_nested_chain_in_children():
    src = "<div>{% if a %}<p>1</p>{% else %}<p>2</p>{% endif %}</div>"
    render = _load(src)
    assert render(a=True) == "<div><p>1</p></div>"
    assert render(a=False) == "<div><p>2</p></div>"


# --- HTML-aware enforcement --------------------------------------------------


def test_straddle_rejected():
    # A block branch must contain balanced HTML — an element opened inside
    # the branch must close inside it.
    with pytest.raises(ParseError, match="balanced HTML"):
        _compile_string("{% if a %}<div>{% endif %}text</div>")


def test_straddle_across_branches_rejected():
    with pytest.raises(ParseError, match="not closed"):
        _compile_string("{% if a %}<div>{% else %}<div>{% endif %}x</div>")


def test_block_tag_inside_start_tag_rejected():
    # `{% %}` can't appear loose in a start tag — conditional attributes
    # use an expression value instead.
    with pytest.raises(TokenizeError, match="start tag"):
        _compile_string("<button {% if x %}disabled{% endif %}>x</button>")


def test_endtag_closing_across_block_rejected():
    with pytest.raises(ParseError, match="balanced HTML"):
        _compile_string("<div>{% if a %}x</div>{% endif %}")


def test_unknown_block_keyword_rejected():
    with pytest.raises(ParseError, match="unknown block tag"):
        _compile_string("{% while x %}y{% endwhile %}")


# --- directives are gone -----------------------------------------------------


def test_if_directive_attribute_is_not_consumed():
    # `:if` is no longer a directive — it renders as an ordinary attribute.
    out = _load('<p :if="x">hi</p>')()
    assert out == '<p :if="x">hi</p>'


def test_for_directive_attribute_is_not_consumed():
    out = _load('<li :for="x in xs">hi</li>')()
    assert out == '<li :for="x in xs">hi</li>'


def test_template_is_an_ordinary_element():
    # `<template>` no longer has transparent-fragment behavior.
    out = _load("<template><p>x</p></template>")()
    assert out == "<template><p>x</p></template>"


# --- {% raw %} literal regions -----------------------------------------------


def test_raw_emits_literal_block_delimiters():
    out = _load("<p>{% raw %}{% if x %}{{ y }}{% endraw %}</p>")()
    assert out == "<p>{% if x %}{{ y }}</p>"


# --- components: frontmatter parsing -----------------------------------------


def test_parse_components_default_name():
    assert parse_components(["components/Card"]) == {"Card": "components/Card"}


def test_parse_components_as_alias():
    assert parse_components(["base as Base"]) == {"Base": "base"}


def test_parse_components_empty_and_none():
    assert parse_components(None) == {}
    assert parse_components([]) == {}


def test_parse_components_rejects_non_pascalcase():
    with pytest.raises(ComponentsError, match="PascalCase"):
        parse_components(["components/card"])


def test_parse_components_rejects_collision():
    with pytest.raises(ComponentsError, match="same"):
        parse_components(["a/Card", "b/Card"])


def test_parse_components_rejects_non_list():
    with pytest.raises(ComponentsError, match="list"):
        parse_components("components/Card")


# --- PascalCase component tags -----------------------------------------------


def test_component_tag_basic(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": ("---\ncomponents:\n  - ./Card\n---\n<Card />"),
            "Card": "<p>card body</p>",
        },
    )
    assert _compile_path(paths["page"])() == "<p>card body</p>"


def test_component_tag_with_attrs(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": ('---\ncomponents:\n  - ./Card\n---\n<Card title="Hello" />'),
            "Card": "---\nattrs:\n  title: str\n---\n<h1>{{ title }}</h1>",
        },
    )
    assert _compile_path(paths["page"])() == "<h1>Hello</h1>"


def test_component_tag_with_expression_attr(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": ("---\ncomponents:\n  - ./Card\n---\n<Card title={{ name }} />"),
            "Card": "---\nattrs:\n  title: str\n---\n<h1>{{ title }}</h1>",
        },
    )
    assert _compile_path(paths["page"])(name="Ada") == "<h1>Ada</h1>"


def test_component_tag_with_children_as_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": ("---\ncomponents:\n  - ./Card\n---\n<Card><p>body</p></Card>"),
            "Card": "---\nslots:\n  default: Markup\n---\n<div>{{ children }}</div>",
        },
    )
    assert _compile_path(paths["page"])() == "<div><p>body</p></div>"


def test_component_tag_with_named_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": (
                "---\ncomponents:\n  - ./Card\n---\n"
                '<Card>{% slot "title" %}<h1>T</h1>{% endslot %}<p>body</p></Card>'
            ),
            "Card": (
                "---\nslots:\n  title: Markup\n  default: Markup\n---\n"
                "<div>{{ title }}|{{ children }}</div>"
            ),
        },
    )
    assert _compile_path(paths["page"])() == "<div><h1>T</h1>|<p>body</p></div>"


def test_component_tag_with_as_alias(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": ("---\ncomponents:\n  - ./base as Base\n---\n<Base />"),
            "base": "<main>layout</main>",
        },
    )
    assert _compile_path(paths["page"])() == "<main>layout</main>"


def test_unknown_component_tag_rejected(tmp_path):
    paths = _write_templates(
        tmp_path,
        {"page": "<Card />"},
    )
    with pytest.raises(ParseError, match="unknown component"):
        _compile_path(paths["page"])


def test_component_tag_in_for_loop(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": (
                "---\ncomponents:\n  - ./Card\n---\n"
                "{% for x in items %}<Card title={{ x }} />{% endfor %}"
            ),
            "Card": "---\nattrs:\n  title: str\n---\n<h1>{{ title }}</h1>",
        },
    )
    out = _compile_path(paths["page"])(items=["a", "b"])
    assert out == "<h1>a</h1><h1>b</h1>"


# --- {% slot %} blocks -------------------------------------------------------


def test_slot_block_routes_content(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "---\ncomponents:\n  - ./Card\n---\n"
                "<Card>"
                '{% slot "header" %}H{% endslot %}'
                "<p>body</p>"
                "</Card>"
            ),
            "Card": (
                "---\nslots:\n  header: Markup\n  default: Markup\n---\n"
                "<div>{{ header }}|{{ children }}</div>"
            ),
        },
    )
    assert _compile_path(paths["parent"])() == "<div>H|<p>body</p></div>"


def test_slot_block_with_element(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "---\ncomponents:\n  - ./Card\n---\n"
                '<Card>{% slot "header" %}<div>H</div>{% endslot %}</Card>'
            ),
            "Card": "---\nslots:\n  header: Markup\n---\n<section>{{ header }}</section>",
        },
    )
    assert _compile_path(paths["parent"])() == "<section><div>H</div></section>"


def test_slot_block_groups_multiple_elements(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "---\ncomponents:\n  - ./Card\n---\n"
                '<Card>{% slot "header" %}<b>A</b><b>B</b>{% endslot %}</Card>'
            ),
            "Card": "---\nslots:\n  header: Markup\n---\n<section>{{ header }}</section>",
        },
    )
    assert _compile_path(paths["parent"])() == "<section><b>A</b><b>B</b></section>"


def test_slot_block_outside_component_rejected():
    with pytest.raises(CompileError, match="component tag"):
        _compile_string('{% slot "header" %}H{% endslot %}')


def test_slot_name_must_be_quoted():
    with pytest.raises(ParseError, match="quoted string"):
        _compile_string("<div>{% slot header %}H{% endslot %}</div>")


def test_unclosed_slot_rejected():
    with pytest.raises(ParseError, match="Unclosed `{% slot %}`"):
        _compile_string('<div>{% slot "header" %}H')
