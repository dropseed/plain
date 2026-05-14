"""Public contract: formatting a template never changes its rendered output.

A user-visible promise. `plain html format` is meant to canonicalize
source layout only — the bytes a browser parses must be DOM-equivalent
to the unformatted source's rendered bytes. Anything else is a
regression in the formatter, not a stylistic choice.

The test renders a hand-curated `(template, context)` fixture list
both unformatted and formatted, parses each output with html5lib, and
asserts the resulting DOM trees match (after collapsing whitespace
where the spec allows formatters to add or remove it, and folding
boolean-attribute values to a canonical sentinel).

Add a fixture when locking in a render-time behavior that source-level
tests (`tests/internal/test_format_*`) can't reach — autoescape,
expression evaluation, inline-in-block whitespace, boolean-attribute
collapse, etc.
"""

from __future__ import annotations

from typing import Any

import html5lib
import pytest

from plain.html.engine import render_source
from plain.html.format import format_source
from plain.html.whitespace import is_verbatim

# Each fixture is (id, template_source, context). The id becomes the
# pytest case name.
FIXTURES: list[tuple[str, str, dict[str, Any]]] = [
    (
        "inline_text_with_expression",
        "<p>Hello, <strong>{name}</strong>!</p>",
        {"name": "Dave"},
    ),
    (
        "for_loop_in_table",
        '<table><tr :for={row in rows}><td>{row["cell"]}</td></tr></table>',
        {"rows": [{"cell": "a"}, {"cell": "b"}, {"cell": "c"}]},
    ),
    (
        "if_block",
        "<div><p :if={ok}>shown</p><p :if={not ok}>hidden</p></div>",
        {"ok": True},
    ),
    (
        "mixed_inline_and_block_children",
        "<section><h1>Title</h1><p>Lead <em>emphasis</em> text.</p></section>",
        {},
    ),
    (
        "pre_with_expression",
        "<pre>{name}\n  preserved\n    indent</pre>",
        {"name": "value"},
    ),
    (
        "boolean_and_dynamic_attrs",
        '<input type="text" disabled="disabled" data-id={user_id}>',
        {"user_id": 42},
    ),
    (
        "long_attributes_with_text",
        '<a href="/u/{user.id}/p" class="btn btn-primary btn-sm" data-x="y" data-z="w">click {label}</a>',
        {"user": type("U", (), {"id": 7})(), "label": "here"},
    ),
    (
        "for_with_tuple_target",
        "<ul><li :for={(i, name) in enumerate(names)}>{i}: {name}</li></ul>",
        {"names": ["alpha", "beta"]},
    ),
    (
        "html_comment_alongside_blocks",
        "<div><!-- header --><h1>Title</h1><p>Body</p></div>",
        {},
    ),
    (
        "void_element_with_expression_attr",
        '<form><input type="text" name="q" value={query}></form>',
        {"query": "hello"},
    ),
]


@pytest.mark.parametrize(
    ("name", "source", "context"), FIXTURES, ids=[f[0] for f in FIXTURES]
)
def test_rendered_dom_equivalence(
    name: str, source: str, context: dict[str, Any]
) -> None:
    rendered_src = render_source(source, context)
    rendered_fmt = render_source(format_source(source), context)

    src_tree = _normalize(_parse_fragment(rendered_src))
    fmt_tree = _normalize(_parse_fragment(rendered_fmt))

    assert src_tree == fmt_tree, (
        f"\nfixture: {name}"
        f"\n--- rendered source ---\n{rendered_src}"
        f"\n--- rendered formatted ---\n{rendered_fmt}"
    )


def _parse_fragment(html: str) -> Any:
    return html5lib.parseFragment(
        html, treebuilder="etree", namespaceHTMLElements=False
    )


_BOOLEAN_ATTRS = frozenset(
    {
        "allowfullscreen",
        "async",
        "autofocus",
        "autoplay",
        "checked",
        "controls",
        "default",
        "defer",
        "disabled",
        "formnovalidate",
        "hidden",
        "inert",
        "ismap",
        "itemscope",
        "loop",
        "multiple",
        "muted",
        "nomodule",
        "novalidate",
        "open",
        "playsinline",
        "readonly",
        "required",
        "reversed",
        "selected",
    }
)


def _normalize(elem: Any, *, inside_verbatim: bool = False) -> Any:
    tag = _local_tag(elem)
    verbatim = inside_verbatim or is_verbatim(tag.lower())

    # Boolean attributes: `disabled`, `disabled=""`, and `disabled="disabled"`
    # are equivalent to a browser. Collapse the value to a sentinel so the
    # formatter's canonical-form choice doesn't perturb the comparison.
    attrs = tuple(
        sorted(
            (k, "" if k.lower() in _BOOLEAN_ATTRS else v)
            for k, v in elem.attrib.items()
        )
    )
    children: list[Any] = []

    leading = elem.text or ""
    if leading:
        normalized = leading if verbatim else _collapse(leading)
        if normalized:
            children.append(("TEXT", normalized))

    for child in elem:
        if _is_comment(child):
            tail = child.tail or ""
            if tail:
                normalized = tail if verbatim else _collapse(tail)
                if normalized:
                    children.append(("TEXT", normalized))
            continue

        children.append(_normalize(child, inside_verbatim=verbatim))

        tail = child.tail or ""
        if tail:
            normalized = tail if verbatim else _collapse(tail)
            if normalized:
                children.append(("TEXT", normalized))

    return (tag, attrs, tuple(children))


def _local_tag(elem: Any) -> str:
    tag = elem.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)


def _is_comment(elem: Any) -> bool:
    tag = getattr(elem, "tag", None)
    return callable(tag)


def _collapse(text: str) -> str:
    return " ".join(text.split())
