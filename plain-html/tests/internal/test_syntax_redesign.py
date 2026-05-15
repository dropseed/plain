"""Tests for the syntax-redesign additions.

Covers the additive engine changes:
  - `:for` comprehension-clause filters
  - `:elif` / `:else` conditional chains and their error cases
  - `components:` frontmatter + PascalCase component tags
  - the `:slot` directive

These exercise behavior at the parse + compile + render layer, the same
style as `test_compiler.py`.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from plain.html.compiler import CompileSession
from plain.html.components import ComponentsError, parse_components
from plain.html.parser import ParseError


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


# --- :for comprehension-clause filter ---------------------------------------


def test_for_filter_basic():
    out = _load("<li :for={x in items if x > 2}>{x}</li>")(items=[1, 2, 3, 4])
    assert out == "<li>3</li><li>4</li>"


def test_for_filter_with_tuple_target():
    src = "<li :for={(i, x) in enumerate(items) if i % 2 == 0}>{x}</li>"
    out = _load(src)(items=["a", "b", "c", "d"])
    assert out == "<li>a</li><li>c</li>"


def test_for_filter_multiple_ifs():
    src = "<li :for={x in items if x > 1 if x < 4}>{x}</li>"
    out = _load(src)(items=[0, 1, 2, 3, 4, 5])
    assert out == "<li>2</li><li>3</li>"


def test_for_nested_for_clause_rejected():
    with pytest.raises(ParseError, match="one `for` clause"):
        _compile_string("<li :for={x in xs for y in ys}>{x}</li>")


def test_for_filter_does_not_break_template_tag():
    out = _load("<template :for={x in items if x}>{x}</template>")(items=[0, 1, 0, 2])
    assert out == "12"


# --- :elif / :else chains ----------------------------------------------------


def test_if_elif_else_first_branch():
    render = _load("<p :if={n == 1}>one</p><p :elif={n == 2}>two</p><p :else>many</p>")
    assert render(n=1) == "<p>one</p>"


def test_if_elif_else_middle_branch():
    render = _load("<p :if={n == 1}>one</p><p :elif={n == 2}>two</p><p :else>many</p>")
    assert render(n=2) == "<p>two</p>"


def test_if_elif_else_else_branch():
    render = _load("<p :if={n == 1}>one</p><p :elif={n == 2}>two</p><p :else>many</p>")
    assert render(n=9) == "<p>many</p>"


def test_lone_if_still_works():
    render = _load("<p :if={show}>hi</p>")
    assert render(show=True) == "<p>hi</p>"
    assert render(show=False) == ""


def test_if_else_without_elif():
    render = _load("<p :if={ok}>yes</p><p :else>no</p>")
    assert render(ok=True) == "<p>yes</p>"
    assert render(ok=False) == "<p>no</p>"


def test_chain_skips_whitespace_and_comments():
    src = "<p :if={ok}>y</p>\n  <!-- between -->\n<p :else>n</p>"
    render = _load(src)
    assert render(ok=True) == "<p>y</p>"
    assert render(ok=False) == "<p>n</p>"


def test_elif_with_for_loop_in_branch():
    src = "<p :if={mode == 'a'}>A</p><ul :elif={mode == 'b'}><li :for={x in xs}>{x}</li></ul>"
    render = _load(src)
    assert render(mode="a", xs=[]) == "<p>A</p>"
    assert render(mode="b", xs=[1, 2]) == "<ul><li>1</li><li>2</li></ul>"


def test_orphan_elif_rejected():
    with pytest.raises(ParseError, match=":elif"):
        _compile_string("<p>x</p><p :elif={y}>z</p>")


def test_orphan_else_rejected():
    with pytest.raises(ParseError, match=":else"):
        _compile_string("<p>x</p><p :else>z</p>")


def test_elif_after_else_rejected():
    with pytest.raises(ParseError, match=":elif"):
        _compile_string("<p :if={a}>1</p><p :else>2</p><p :elif={b}>3</p>")


def test_two_else_rejected():
    with pytest.raises(ParseError, match=":else"):
        _compile_string("<p :if={a}>1</p><p :else>2</p><p :else>3</p>")


def test_else_with_value_rejected():
    with pytest.raises(ParseError, match=":else"):
        _compile_string("<p :if={a}>1</p><p :else={x}>2</p>")


def test_conditional_and_for_same_element_rejected():
    with pytest.raises(ParseError, match="conditional directive"):
        _compile_string("<li :elif={a} :for={x in xs}>{x}</li>")


def test_nested_chain_in_children():
    src = "<div><p :if={a}>1</p><p :else>2</p></div>"
    render = _load(src)
    assert render(a=True) == "<div><p>1</p></div>"
    assert render(a=False) == "<div><p>2</p></div>"


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
            "Card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
    )
    assert _compile_path(paths["page"])() == "<h1>Hello</h1>"


def test_component_tag_with_children_as_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": ("---\ncomponents:\n  - ./Card\n---\n<Card><p>body</p></Card>"),
            "Card": "---\nslots:\n  default: Markup\n---\n<div>{children}</div>",
        },
    )
    assert _compile_path(paths["page"])() == "<div><p>body</p></div>"


def test_component_tag_with_named_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "page": (
                "---\ncomponents:\n  - ./Card\n---\n"
                '<Card><h1 :slot="title">T</h1><p>body</p></Card>'
            ),
            "Card": (
                "---\nslots:\n  title: Markup\n  default: Markup\n---\n"
                "<div>{title}|{children}</div>"
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
                "<Card :for={x in items} title={x} />"
            ),
            "Card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
    )
    out = _compile_path(paths["page"])(items=["a", "b"])
    assert out == "<h1>a</h1><h1>b</h1>"


# --- :slot directive ---------------------------------------------------------


def test_slot_directive_routes_content(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "---\ncomponents:\n  - ./Card\n---\n"
                "<Card>"
                '<template :slot="header">H</template>'
                "<p>body</p>"
                "</Card>"
            ),
            "Card": (
                "---\nslots:\n  header: Markup\n  default: Markup\n---\n"
                "<div>{header}|{children}</div>"
            ),
        },
    )
    assert _compile_path(paths["parent"])() == "<div>H|<p>body</p></div>"


def test_slot_directive_on_element(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "---\ncomponents:\n  - ./Card\n---\n"
                '<Card><div :slot="header">H</div></Card>'
            ),
            "Card": "---\nslots:\n  header: Markup\n---\n<section>{header}</section>",
        },
    )
    assert _compile_path(paths["parent"])() == "<section><div>H</div></section>"


def test_template_slot_wrapper_dropped(tmp_path):
    # `<template :slot="x">` contributes only its inner children; the
    # `<template>` wrapper itself is not rendered.
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "---\ncomponents:\n  - ./Card\n---\n"
                '<Card><template :slot="header">H</template></Card>'
            ),
            "Card": "---\nslots:\n  header: Markup\n---\n<section>{header}</section>",
        },
    )
    assert _compile_path(paths["parent"])() == "<section>H</section>"
