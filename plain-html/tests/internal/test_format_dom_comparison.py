"""DOM-level conformance test for the formatter (tier-2).

Parses every `.html` template in the repo with html5lib (the WHATWG-spec
parser, the same parsing rules a browser applies) and asserts that
`format_source(x)` produces an output that parses to the same DOM tree
as `x`.

html5lib doesn't understand `{expr}` template syntax — expressions
containing `=`, `>`, or whitespace wreck attribute parsing. We mask
expressions and template comments with content-hashed placeholders
before parsing, so matching expressions in source and formatted output
collapse to the same token regardless of position.

What this catches that the corpus property test misses:

- Void-element-form changes (`<br>` vs `<br/>`) — same DOM, different
  bytes.
- Attribute-order changes (we sort attributes when comparing).
- Inter-tag whitespace differences in flow content (we drop
  whitespace-only text nodes).
- Character-entity decoding differences.

Templates whose own source cannot be tokenized or formatted xfail so
in-flux work doesn't block the suite.
"""

from __future__ import annotations

import hashlib
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

    try:
        formatted = format_source(source)
    except (TokenizeError, ParseError) as e:
        pytest.xfail(f"engine cannot parse {path.name}: {e}")  # ty: ignore[too-many-positional-arguments]

    src_body = _mask(source[_body_offset(source) :])
    fmt_body = _mask(formatted[_body_offset(formatted) :])

    src_tree = _normalize(_parse_fragment(src_body))
    fmt_tree = _normalize(_parse_fragment(fmt_body))

    assert src_tree == fmt_tree, f"DOM diverged after format in {path}"


def _mask(body: str) -> str:
    """Replace `{...}` and `{# ... #}` with content-hashed placeholders.

    Matching expressions in source and formatted output get the same
    placeholder regardless of position, so directive reordering and
    other formatter normalizations don't perturb the comparison.

    `{{` / `}}` (literal-brace escapes) are passed through unchanged.
    """
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        if body.startswith("{#", i):
            end = body.find("#}", i + 2)
            if end == -1:
                out.append(body[i:])
                break
            content = body[i + 2 : end]
            out.append(_placeholder("TC", content))
            i = end + 2
            continue
        if body.startswith("{{", i) or body.startswith("}}", i):
            out.append(body[i : i + 2])
            i += 2
            continue
        if body[i] == "{":
            j = _find_matching_brace(body, i)
            content = body[i + 1 : j]
            out.append(_placeholder("EX", content))
            i = j + 1
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


def _find_matching_brace(body: str, start: int) -> int:
    """Return the index of the `}` that closes the `{` at `start`.

    Brace-depth tracking with string-quote awareness mirrors the
    tokenizer's `_consume_expr` so nested literals don't fool us.
    """
    assert body[start] == "{"
    i = start + 1
    n = len(body)
    depth = 1
    quote: str | None = None
    while i < n:
        c = body[i]
        if quote is not None:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ('"', "'"):
            quote = c
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _placeholder(kind: str, content: str) -> str:
    h = hashlib.sha1(content.encode()).hexdigest()[:10]
    return f"__{kind}_{h}__"


def _parse_fragment(html: str) -> Any:
    return html5lib.parseFragment(
        html, treebuilder="etree", namespaceHTMLElements=False
    )


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
    tag = elem.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)


def _is_comment(elem: Any) -> bool:
    tag = getattr(elem, "tag", None)
    return callable(tag)


def _collapse(text: str) -> str:
    return " ".join(text.split())
