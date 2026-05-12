"""Phase 0 smoke tests for the tracer-bullet engine.

Internal tests — these pin the current interpreter behavior so Phase 5's
compile-to-Python rewrite can be verified against the same expectations.
"""

from __future__ import annotations

import pytest

from plain.html import Markup, render_source
from plain.html.parser import ParseError
from plain.html.tokenizer import TokenizeError


def test_plain_text():
    assert render_source("<p>hello</p>") == "<p>hello</p>"


def test_expression_in_text_is_escaped():
    out = render_source("<p>{x}</p>", {"x": "<b>bold</b>"})
    assert out == "<p>&lt;b&gt;bold&lt;/b&gt;</p>"


def test_markup_bypasses_escape():
    out = render_source("<p>{x}</p>", {"x": Markup("<b>bold</b>")})
    assert out == "<p><b>bold</b></p>"


def test_attribute_expression():
    out = render_source('<a href="/u/{handle}">link</a>', {"handle": "ada"})
    assert out == '<a href="/u/ada">link</a>'


def test_boolean_attribute_true():
    assert render_source("<input disabled={x} />", {"x": True}) == "<input disabled>"


def test_boolean_attribute_false_is_omitted():
    assert render_source("<input disabled={x} />", {"x": False}) == "<input>"


def test_boolean_attribute_none_is_omitted():
    assert render_source("<input disabled={x} />", {"x": None}) == "<input>"


def test_if_directive_true():
    out = render_source("<span :if={ok}>yes</span>", {"ok": True})
    assert out == "<span>yes</span>"


def test_if_directive_false():
    assert render_source("<span :if={ok}>yes</span>", {"ok": False}) == ""


def test_for_directive():
    out = render_source("<li :for={x in xs}>{x}</li>", {"xs": [1, 2, 3]})
    assert out == "<li>1</li><li>2</li><li>3</li>"


def test_for_directive_with_tuple_unpack():
    out = render_source(
        "<tr :for={(k, v) in pairs}><td>{k}</td><td>{v}</td></tr>",
        {"pairs": [("a", 1), ("b", 2)]},
    )
    assert out == "<tr><td>a</td><td>1</td></tr><tr><td>b</td><td>2</td></tr>"


def test_template_fragment_is_transparent():
    out = render_source("<p>x<template :if={ok}>y</template>z</p>", {"ok": True})
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
        render_source("<p>{x</p>")


def test_literal_brace_via_double_brace():
    assert render_source("<p>{{x}}</p>") == "<p>{x}</p>"
