from __future__ import annotations

from plain.html.positions import body_offset, offset_to_line_col


def test_body_offset_with_frontmatter():
    source = "---\nattrs:\n  name: str\n---\n<p>hi</p>\n"
    # Body begins immediately after the closing `---\n`.
    assert source[body_offset(source) :].startswith("<p>hi</p>")


def test_body_offset_without_frontmatter():
    source = "<p>hi</p>\n"
    assert body_offset(source) == 0


def test_offset_to_line_col_first_line():
    source = "hello world"
    assert offset_to_line_col(source, 0) == (1, 1)
    assert offset_to_line_col(source, 6) == (1, 7)


def test_offset_to_line_col_after_newline():
    source = "first\nsecond\nthird"
    # Start of "second" — character after `\n` at offset 5.
    assert offset_to_line_col(source, 6) == (2, 1)
    # "third"
    assert offset_to_line_col(source, 13) == (3, 1)


def test_offset_clamped_to_source_bounds():
    source = "abc"
    assert offset_to_line_col(source, -5) == (1, 1)
    assert offset_to_line_col(source, 999)[0] == 1
