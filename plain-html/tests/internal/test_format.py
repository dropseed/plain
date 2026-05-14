from plain.html.engine import render_source
from plain.html.format import format_source


def test_format_single_element():
    """Single tag with text content survives format unchanged (trailing newline added)."""
    assert format_source("<p>hello</p>") == "<p>hello</p>\n"


def test_format_preserves_inline_whitespace():
    """Phrasing-content children (e.g. `<strong>`) stay on the same line as surrounding text."""
    src = "<p>Hello <strong>world</strong>!</p>"
    assert format_source(src) == "<p>Hello <strong>world</strong>!</p>\n"


def test_format_breaks_block_children():
    """Flow-content children get their own lines with one indent level."""
    src = "<div><p>one</p><p>two</p></div>"
    assert format_source(src) == "<div>\n    <p>one</p>\n    <p>two</p>\n</div>\n"


def test_format_preserves_expression_bytes():
    """Bytes between `{` and `}` are opaque — formatter never edits expression interiors."""
    src = "<p>{user.name | x_or_y(  '  ' )}</p>"
    # The bytes between { and } must be preserved exactly.
    out = format_source(src)
    assert "{user.name | x_or_y(  '  ' )}" in out


def test_format_preserves_template_comments():
    """`{# … #}` template comments round-trip through format."""
    src = "<p>{# keep me #}hi</p>"
    out = format_source(src)
    assert "{# keep me #}" in out


def test_format_preserves_html_comments():
    """`<!-- … -->` HTML comments round-trip through format."""
    src = "<!-- top --><p>hi</p>"
    out = format_source(src)
    assert "<!-- top -->" in out


def test_format_verbatim_preserves_byte_for_byte():
    """`<pre>` body is verbatim — no whitespace mutation inside."""
    src = "<pre>\n  one\n    two\n</pre>"
    assert format_source(src) == "<pre>\n  one\n    two\n</pre>\n"


def test_format_script_body_opaque():
    """`<script>` body is opaque — even `{...}`-looking JS survives untouched."""
    src = "<script>\nconsole.log('{not an expr}');\n</script>"
    assert format_source(src) == src + "\n"


def test_format_preserves_frontmatter_byte_for_byte():
    """The frontmatter block is byte-identical pre- and post-format."""
    src = "---\nattrs:\n  name: str\n---\n<p>{name}</p>"
    out = format_source(src)
    assert out.startswith("---\nattrs:\n  name: str\n---\n")


def test_format_void_element():
    """Void elements (`<img>`) keep their bare form with no trailing slash."""
    assert format_source('<img src="x.png">') == '<img src="x.png">\n'


def test_format_void_element_drops_self_closing_slash():
    """Void elements canonicalize to bare `<img>` regardless of source's `<img/>` / `<img />`."""
    # Per HTML5 spec, the trailing slash on void elements has no effect.
    # Canonical form is bare `<img>`; we normalize source's `<img/>` and
    # `<img />` down to it.
    assert format_source("<img/>") == "<img>\n"
    assert format_source("<img />") == "<img>\n"
    assert format_source("<br/>") == "<br>\n"
    assert format_source('<input type="text"/>') == '<input type="text">\n'


def test_format_non_void_self_closing_preserved():
    """Non-void self-closing tags keep `/>` as a deliberate "no children" marker."""
    # Non-void elements that the parser saw as self-closing keep the
    # `/>` form — useful as a "no children" marker for component-style
    # uses of <template :include="x" />.
    out = format_source('<template :include="x"/>')
    assert "/>" in out


def test_format_self_closing_template():
    """`<template :include="..."></template>` keeps its directive attribute."""
    src = '<template :include="layouts/base"></template>'
    out = format_source(src)
    assert ":include=" in out
    assert "<template" in out


def test_format_directive_if():
    """`:if={expr}` is preserved verbatim as a structured directive attribute."""
    src = "<div :if={ok}>x</div>"
    out = format_source(src)
    assert ":if={ok}" in out


def test_format_directive_for():
    """`:for={x in xs}` is preserved verbatim as a structured directive attribute."""
    src = "<li :for={item in items}>{item}</li>"
    out = format_source(src)
    assert ":for={item in items}" in out


def test_format_directive_for_tuple_target():
    """`:for` with tuple-unpacking targets round-trips exactly."""
    src = "<li :for={i, x in enumerate(items)}>{x}</li>"
    out = format_source(src)
    assert ":for={i, x in enumerate(items)}" in out


def test_format_preserves_reserved_directive_as():
    """`:as={var}` (scoped-slot binding) round-trips even though the engine doesn't act on it yet."""
    # `:as` is the scoped-slot binding from the spec. The engine doesn't
    # act on it yet, but the formatter must round-trip it.
    src = '<template slot="default" :as={item}>{item}</template>'
    out = format_source(src)
    assert ":as={item}" in out
    assert format_source(out) == out


def test_format_preserves_unknown_colon_directive():
    """Unknown `:`-prefixed attributes survive — formatter doesn't erase what it doesn't recognize."""
    # Any `:`-prefixed attribute the parser doesn't recognize is held on
    # the node so the formatter doesn't erase it.
    src = "<div :something={value}>x</div>"
    out = format_source(src)
    assert ":something={value}" in out


def test_format_reescapes_literal_braces_in_text():
    """`{{`/`}}` literal-brace escape survives round-trip (tokenizer decodes; formatter re-encodes)."""
    # Source uses `{{`/`}}` to mean a literal `{`/`}`. Tokenizer decodes
    # them on the way in; formatter must re-encode on the way out or the
    # re-parsed output mistakes them for an expression.
    src = "<pre>{{ literal }}</pre>"
    out = format_source(src)
    assert "{{ literal }}" in out
    # And it must be idempotent.
    assert format_source(out) == out


def test_format_does_not_reescape_braces_in_script_body():
    """`{` inside `<script>` stays single — the tokenizer never decoded it, so don't re-encode."""
    # Script bodies are opaque to the tokenizer — `{` stays `{`, no
    # escape was applied, so the formatter must not double up.
    src = "<script>function f() { return 1; }</script>"
    out = format_source(src)
    assert "function f() { return 1; }" in out
    assert format_source(out) == out


def test_format_boolean_attribute():
    """Bare boolean attributes (`disabled`) stay bare."""
    src = "<input disabled>"
    assert format_source(src) == "<input disabled>\n"


def test_format_collapses_boolean_attribute_value():
    """`disabled="disabled"` normalizes to bare `disabled`."""
    src = '<input disabled="disabled">'
    assert format_source(src) == "<input disabled>\n"


def test_format_does_not_collapse_non_matching_value():
    """Boolean-attribute collapse only fires when value matches attr name verbatim."""
    # Only `attr="attr"` collapses. Different content stays.
    src = '<input data-state="data-state-other">'
    out = format_source(src)
    assert 'data-state="data-state-other"' in out


def test_format_uses_single_quotes_when_value_contains_double():
    """Attribute values containing `"` switch the quoting to `'` to avoid re-escaping."""
    # Compose a value that contains a literal `"`. We hand-build via
    # attribute segments rather than parsing source so we test the
    # emitter directly.
    from plain.html.format import _format_attribute
    from plain.html.tokenizer import Attribute, AttrText

    attr = Attribute(name="data-json", segments=[AttrText('a "quoted" value')])
    assert _format_attribute(attr) == "data-json='a \"quoted\" value'"


def test_format_keeps_double_quotes_when_no_conflict():
    """Default quoting is double — only switch when the value contains `"`."""
    from plain.html.format import _format_attribute
    from plain.html.tokenizer import Attribute, AttrText

    attr = Attribute(name="title", segments=[AttrText("plain value")])
    assert _format_attribute(attr) == 'title="plain value"'


def test_format_attribute_with_expression():
    """Mixed-segment attribute values (text + `{expr}`) round-trip verbatim."""
    src = '<a href="/users/{user.id}/edit">edit</a>'
    out = format_source(src)
    assert 'href="/users/{user.id}/edit"' in out


def test_idempotent_simple():
    """Hard invariant: `format(format(x)) == format(x)` for plain block content."""
    src = "<div><p>one</p><p>two</p></div>"
    once = format_source(src)
    twice = format_source(once)
    assert once == twice


def test_idempotent_inline():
    """Hard invariant: idempotency holds for inline (phrasing-content) cases."""
    src = "<p>Hello <strong>world</strong>!</p>"
    once = format_source(src)
    twice = format_source(once)
    assert once == twice


def test_idempotent_with_frontmatter_and_directives():
    """Hard invariant: idempotency holds when frontmatter and `:for` are in play."""
    src = (
        "---\nattrs:\n  items: list[str]\n---\n"
        "<ul>\n"
        '<li :for={item in items}><span class="row">{item}</span></li>\n'
        "</ul>"
    )
    once = format_source(src)
    twice = format_source(once)
    assert once == twice


def test_render_equivalence_inline_with_text():
    """Hard invariant: `render(format(x)) == render(x)` for inline text content."""
    src = "<p>Hello <strong>world</strong>!</p>"
    assert render_source(format_source(src)) == render_source(src) + "\n"


def test_render_equivalence_with_expression():
    """Hard invariant: render equivalence holds with a `{expr}` interpolation."""
    src = "<p>Hello, {name}!</p>"
    ctx = {"name": "Dave"}
    assert render_source(format_source(src), ctx) == render_source(src, ctx) + "\n"


def _normalize_intertag_whitespace(html: str) -> str:
    # Strip all whitespace that sits between adjacent tags — the relaxed
    # render-equivalence contract permits the formatter to add or remove
    # whitespace there. Text inside tags is left alone.
    import re

    return re.sub(r">\s+<", "><", html.strip())


def test_render_equivalence_with_for_loop():
    """Render-equivalence with `:for` after collapsing inter-tag whitespace."""
    src = "<ul><li :for={x in items}>{x}</li></ul>"
    ctx = {"items": ["a", "b", "c"]}
    out_src = _normalize_intertag_whitespace(render_source(src, ctx))
    out_fmt = _normalize_intertag_whitespace(render_source(format_source(src), ctx))
    assert out_src == out_fmt


def test_short_tag_does_not_wrap():
    """Tags under the 88-column threshold stay on one line."""
    src = '<a href="/x">click</a>'
    assert format_source(src) == '<a href="/x">click</a>\n'


def test_long_tag_wraps_attributes():
    """Tags exceeding 88 columns wrap each attribute onto its own line."""
    src = (
        '<a href="/some/very/long/url/path" class="btn btn-primary btn-large" '
        'data-test="x" data-another="y">click</a>'
    )
    out = format_source(src)
    # Each attribute should land on its own line, indented one level.
    assert "<a\n" in out
    assert '    href="/some/very/long/url/path"' in out
    assert '    class="btn btn-primary btn-large"' in out
    assert ">click</a>" in out


def test_wrapped_open_tag_self_closing():
    """Wrapped void elements keep their closing `>` or `/>` on a final line."""
    src = (
        '<input type="text" name="some-very-long-field-name" '
        'placeholder="please enter your full name here" class="form-input">'
    )
    out = format_source(src)
    assert "<input\n" in out
    # Void/self-closing end-of-tag at outer indent on its own line.
    assert out.rstrip().endswith(">") or out.rstrip().endswith("/>")


def test_wrap_threshold_respects_indent():
    """Wrap decision accounts for ambient indent depth, not just raw line width."""
    # A tag that fits at indent 0 might not fit at deeper indent.
    inner_attrs = '<a href="/foo" class="bar">x</a>'
    src = f"<section><div>{inner_attrs}</div></section>"
    out = format_source(src)
    # Should still format (no crash) and stay idempotent.
    assert format_source(out) == out


def test_idempotent_wrapped_tag():
    """Hard invariant: idempotency holds for the wrapped-attribute layout."""
    src = (
        '<a href="/some/very/long/url/path" class="btn btn-primary btn-large" '
        'data-test="x" data-another="y">click</a>'
    )
    once = format_source(src)
    twice = format_source(once)
    assert once == twice


def test_render_equivalence_pre_preserves_exactly():
    """Hard invariant: `<pre>` verbatim contents render byte-identically post-format."""
    src = "<pre>\n  a\n    b\n</pre>"
    # Verbatim contents must render identically — no whitespace mutation.
    assert render_source(format_source(src)) == render_source(src) + "\n"
