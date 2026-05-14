"""Formatter reorders top-level frontmatter keys to canonical order.

Canonical order: `imports → attrs → slots → (others, original order)`.
Values stay byte-for-byte; only the block-level order changes.
"""

from __future__ import annotations

from plain.html.format import format_source


def test_reorders_slots_before_attrs():
    src = "---\nslots:\n  default: required\nattrs:\n  name: str\n---\n<p>{name}</p>\n"
    out = format_source(src)
    attrs_idx = out.index("attrs:")
    slots_idx = out.index("slots:")
    assert attrs_idx < slots_idx


def test_reorders_attrs_after_imports():
    src = (
        "---\n"
        "attrs:\n"
        "  name: str\n"
        "imports:\n"
        "  - from plain.urls import reverse as url\n"
        "---\n"
        "<p>{name}</p>\n"
    )
    out = format_source(src)
    imports_idx = out.index("imports:")
    attrs_idx = out.index("attrs:")
    assert imports_idx < attrs_idx


def test_unknown_keys_keep_relative_position():
    src = (
        "---\n"
        "extra:\n"
        "  custom: value\n"
        "attrs:\n"
        "  name: str\n"
        "another:\n"
        "  key: value\n"
        "---\n"
        "<p>{name}</p>\n"
    )
    out = format_source(src)
    attrs_idx = out.index("attrs:")
    extra_idx = out.index("extra:")
    another_idx = out.index("another:")
    # attrs comes before unknown keys
    assert attrs_idx < extra_idx
    assert attrs_idx < another_idx
    # unknown keys keep their original order
    assert extra_idx < another_idx


def test_no_frontmatter_unchanged():
    src = "<p>Hello</p>\n"
    assert format_source(src) == "<p>Hello</p>\n"


def test_already_canonical_unchanged():
    src = (
        "---\n"
        "imports:\n"
        "  - from plain.urls import reverse as url\n"
        "attrs:\n"
        "  name: str\n"
        "slots:\n"
        "  default: required\n"
        "---\n"
        "<p>{name}</p>\n"
    )
    assert format_source(src) == src


def test_value_bytes_preserved():
    """Reordering must not touch the bytes of each section's value."""
    src = (
        "---\n"
        "attrs:\n"
        "  name:  str   = 'hi'\n"  # weird whitespace inside the value
        "  count: int = 0\n"
        "imports:\n"
        "  - from datetime import datetime\n"
        "---\n"
        "<p>{name}</p>\n"
    )
    out = format_source(src)
    # The attrs block content survives unchanged.
    assert "  name:  str   = 'hi'\n" in out
    assert "  count: int = 0\n" in out
    # The imports block content survives unchanged.
    assert "  - from datetime import datetime\n" in out


def test_idempotent_on_already_formatted():
    src = "---\nslots:\n  default: required\nattrs:\n  name: str\n---\n<p>{name}</p>\n"
    once = format_source(src)
    twice = format_source(once)
    assert once == twice


def test_blank_line_inside_section_preserved():
    src = (
        "---\n"
        "imports:\n"
        "  - from plain.urls import reverse as url\n"
        "\n"
        "  - from datetime import datetime\n"
        "attrs:\n"
        "  name: str\n"
        "---\n"
        "<p>{name}</p>\n"
    )
    out = format_source(src)
    # Both imports survive, in order, with the blank line between them.
    assert (
        "imports:\n"
        "  - from plain.urls import reverse as url\n"
        "\n"
        "  - from datetime import datetime\n"
    ) in out
