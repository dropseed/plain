"""Compiler-render smoke tests via the `render_source` entry point.

Internal tests — these pin specific in-process behaviors of the compiler
(token errors, parse errors, raw regions, boolean-attribute collapse,
block control flow, etc.) by calling `render_source(...)` directly. The
user-visible contract for `Template`/`render`/`Markup` lives in
`tests/public/test_template.py`.
"""

from __future__ import annotations

import pytest

from plain.html import Markup, render_source
from plain.html.parser import ParseError
from plain.html.tokenizer import TokenizeError


def test_plain_text():
    assert render_source("<p>hello</p>") == "<p>hello</p>"


def test_expression_in_text_is_escaped():
    out = render_source("<p>{{ x }}</p>", {"x": "<b>bold</b>"})
    assert out == "<p>&lt;b&gt;bold&lt;/b&gt;</p>"


def test_markup_bypasses_escape():
    out = render_source("<p>{{ x }}</p>", {"x": Markup("<b>bold</b>")})
    assert out == "<p><b>bold</b></p>"


def test_attribute_expression():
    out = render_source('<a href="/u/{{ handle }}">link</a>', {"handle": "ada"})
    assert out == '<a href="/u/ada">link</a>'


def test_boolean_attribute_true():
    assert (
        render_source("<input disabled={{ x }} />", {"x": True}) == "<input disabled>"
    )


def test_boolean_attribute_false_is_omitted():
    assert render_source("<input disabled={{ x }} />", {"x": False}) == "<input>"


def test_boolean_attribute_none_is_omitted():
    assert render_source("<input disabled={{ x }} />", {"x": None}) == "<input>"


def test_if_block_true():
    out = render_source("{% if ok %}<span>yes</span>{% endif %}", {"ok": True})
    assert out == "<span>yes</span>"


def test_if_block_false():
    assert render_source("{% if ok %}<span>yes</span>{% endif %}", {"ok": False}) == ""


def test_for_block():
    out = render_source(
        "{% for x in xs %}<li>{{ x }}</li>{% endfor %}", {"xs": [1, 2, 3]}
    )
    assert out == "<li>1</li><li>2</li><li>3</li>"


def test_for_block_with_tuple_unpack():
    out = render_source(
        "{% for (k, v) in pairs %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}",
        {"pairs": [("a", 1), ("b", 2)]},
    )
    assert out == "<tr><td>a</td><td>1</td></tr><tr><td>b</td><td>2</td></tr>"


def test_if_block_with_no_wrapper_element():
    out = render_source("<p>x{% if ok %}y{% endif %}z</p>", {"ok": True})
    assert out == "<p>xyz</p>"


def test_html_comment_preserved():
    assert render_source("<!-- keep -->") == "<!-- keep -->"


def test_template_comment_stripped():
    assert render_source("<p>{# strip #}hi</p>") == "<p>hi</p>"


def test_doctype_preserved():
    assert render_source("<!DOCTYPE html><p>x</p>") == "<!DOCTYPE html><p>x</p>"


def test_void_elements_have_no_close_tag():
    assert render_source('<img src="x.png" />') == '<img src="x.png">'
    assert render_source("<br>") == "<br>"


def test_mismatched_tags_error():
    with pytest.raises(ParseError):
        render_source("<a></b>")


def test_unterminated_expression_error():
    with pytest.raises(TokenizeError):
        render_source("<p>{{ x</p>")


def test_single_braces_are_literal_text():
    assert render_source("<p>{x}</p>") == "<p>{x}</p>"


def test_raw_block_emits_literal_delimiters():
    assert render_source("<p>{% raw %}{{ x }}{% endraw %}</p>") == "<p>{{ x }}</p>"
