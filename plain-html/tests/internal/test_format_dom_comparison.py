"""DOM-level conformance test for the formatter (tier-2).

Parses every `.html` template in the repo as an HTML fragment with
html5lib (the WHATWG-spec parser, the same parsing rules a browser
applies), and asserts that `format_source(x)` produces an output that
parses to the same DOM tree as `x`.

What this catches that the corpus property test misses:

- Void-element-form changes (`<br>` vs `<br/>`) — same DOM, different
  bytes; the byte-comparison would call them different.
- Attribute-order changes that survive the byte-equivalent path but
  show up at the DOM level (we sort here to compare).
- Inter-tag whitespace differences in flow content (we drop
  whitespace-only text nodes from both sides).
- Character-entity decoding differences.

Templates whose own source cannot be tokenized or formatted xfail so
in-flux work doesn't block the suite. Comments are dropped from the
comparison — formatter preserves them; html5lib parses them; checking
that they round-trip is the corpus test's job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import html5lib
import pytest

from plain.html.format import _body_offset, format_source
from plain.html.parser import ParseError
from plain.html.tokenizer import TokenizeError
from plain.html.whitespace import is_verbatim

REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_MARKER = REPO_ROOT / "plain-html-implementation-plan.md"

pytestmark = pytest.mark.skipif(
    not _REPO_MARKER.exists(),
    reason="DOM comparison test only runs from the repo checkout",
)


def _discover_templates() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("html/*"):
        if not path.is_dir():
            continue
        files.extend(path.rglob("*.html"))
    return sorted(set(files))


_TEMPLATES = _discover_templates()


@pytest.mark.parametrize(
    "path", _TEMPLATES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_dom_equivalence(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    body = source[_body_offset(source) :]

    try:
        formatted = format_source(source)
    except (TokenizeError, ParseError) as e:
        pytest.xfail(f"engine cannot parse {path.name}: {e}")  # ty: ignore[too-many-positional-arguments]
    formatted_body = formatted[_body_offset(formatted) :]

    src_tree = _normalize(_parse_fragment(body))
    fmt_tree = _normalize(_parse_fragment(formatted_body))

    assert src_tree == fmt_tree, f"DOM diverged after format in {path}"


def _parse_fragment(html: str) -> Any:
    return html5lib.parseFragment(html, treebuilder="etree", namespaceHTMLElements=False)


def _normalize(elem: Any, *, inside_verbatim: bool = False) -> Any:
    """Return a (tag, attrs, children) tuple for stable comparison.

    Drops whitespace-only text in flow content, preserves text exactly
    inside verbatim parents (`<pre>`, `<textarea>`, `<script>`, `<style>`),
    sorts attributes, and ignores HTML/template comments.
    """
    tag = _local_tag(elem)
    verbatim = inside_verbatim or is_verbatim(tag.lower())

    attrs = tuple(sorted(elem.attrib.items()))
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
    """Return the element's local tag name (strip namespaces if any).

    With `namespaceHTMLElements=False` html5lib already returns plain
    names, but `parseFragment` wraps the result in a synthetic
    `DOCUMENT_FRAGMENT` element — that's fine; both sides have it.
    """
    tag = elem.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)


def _is_comment(elem: Any) -> bool:
    tag = getattr(elem, "tag", None)
    return callable(tag)  # etree comments have a factory function as `.tag`


def _collapse(text: str) -> str:
    return " ".join(text.split())
