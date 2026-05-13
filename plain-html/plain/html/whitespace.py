"""Whitespace-sensitivity classification for HTML elements.

The formatter must never inject newlines around elements where whitespace
is significant for rendered layout. The classification follows WHATWG
content categories:

- **Verbatim** (`<pre>`, `<textarea>`, `<script>`, `<style>`): everything
  inside is preserved byte-for-byte. The formatter does not even descend.
- **Inline** (phrasing content): `<a>`, `<span>`, `<strong>`, etc. The
  formatter may not introduce or strip whitespace inside or around these
  elements when they appear as flow children, because doing so changes
  rendered text spacing.
- **Block** (flow content not in the inline set): `<div>`, `<p>`,
  `<section>`, etc. The formatter is free to wrap children onto their
  own lines.

Reference: https://html.spec.whatwg.org/multipage/dom.html#content-categories

Source of truth for the inline set is the WHATWG "phrasing content"
category, with elements that are *also* embedded or interactive content
included (they participate in inline layout). Any element not in either
the verbatim or inline set is treated as block.
"""

from __future__ import annotations

VERBATIM_ELEMENTS: frozenset[str] = frozenset(
    {
        "pre",
        "textarea",
        "script",
        "style",
    }
)

INLINE_ELEMENTS: frozenset[str] = frozenset(
    {
        "a",
        "abbr",
        "audio",
        "b",
        "bdi",
        "bdo",
        "br",
        "button",
        "canvas",
        "cite",
        "code",
        "data",
        "datalist",
        "del",
        "dfn",
        "em",
        "embed",
        "i",
        "iframe",
        "img",
        "input",
        "ins",
        "kbd",
        "label",
        "map",
        "mark",
        "math",
        "meter",
        "noscript",
        "object",
        "output",
        "picture",
        "progress",
        "q",
        "ruby",
        "s",
        "samp",
        "select",
        "slot",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "svg",
        "template",
        "time",
        "u",
        "var",
        "video",
        "wbr",
    }
)


def is_verbatim(tag: str) -> bool:
    """Children of this element are preserved byte-for-byte."""
    return tag in VERBATIM_ELEMENTS


def is_inline(tag: str) -> bool:
    """Element participates in inline (phrasing) layout."""
    return tag in INLINE_ELEMENTS


def is_block(tag: str) -> bool:
    """Element is a flow/block container — safe to wrap children."""
    return tag not in INLINE_ELEMENTS and tag not in VERBATIM_ELEMENTS
