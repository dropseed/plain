"""Compiler-render smoke tests via the `render_source` entry point.

Internal tests — these pin specific in-process behaviors of the compiler
(token errors, parse errors, raw regions, boolean-attribute collapse,
block control flow, etc.) by calling `render_source(...)` directly. The
user-visible contract for `Template`/`render`/`Markup` lives in
`tests/public/test_template.py`.
"""

from __future__ import annotations

import pytest

from plain.html import Markup, render_source, render_text_source
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


# --- text mode (render_text_source) -----------------------------------------


def test_text_mode_interpolates_expressions():
    assert render_text_source("# {{ title }}", {"title": "Guide"}) == "# Guide"


def test_text_mode_does_not_html_escape():
    # Text mode output is not HTML — values must not be escaped.
    assert render_text_source("{{ v }}", {"v": "a & b <c>"}) == "a & b <c>"


def test_text_mode_leaves_html_like_text_literal():
    # Placeholder <tags>, autolinks, unbalanced fragments — all literal.
    src = "run `cmd --app <app>` see <https://x.com> and <div>unclosed"
    assert render_text_source(src) == src


def test_text_mode_block_tags_are_literal():
    # `{% if %}` / `{% for %}` are HTML-mode only; literal text here.
    assert render_text_source("{% if x %}y{% endif %}") == "{% if x %}y{% endif %}"


def test_text_mode_raw_block_passes_delimiters_through():
    assert render_text_source("{% raw %}{{ x }}{% endraw %}") == "{{ x }}"


def test_text_mode_drops_comments():
    assert render_text_source("a{# note #}b") == "ab"


def test_text_mode_none_renders_empty():
    assert render_text_source("[{{ v }}]", {"v": None}) == "[]"


def test_source_override_bypasses_process_cache(tmp_path):
    """`render_source(..., source_path=...)` reflects the in-memory source
    on every call. The process cache is keyed by path alone, so compiling
    a path once must not pin a stale render for a later, different source.
    """
    from plain.html.compiler import clear_process_cache

    clear_process_cache()
    path = tmp_path / "page.html"

    assert render_source("<p>first</p>", source_path=path) == "<p>first</p>"
    assert render_source("<p>second</p>", source_path=path) == "<p>second</p>"
