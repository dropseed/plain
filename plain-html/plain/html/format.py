"""Formatter for `.html` templates (Phase 9.5).

Public API:

    format_source(source: str, *, indent_size: int = 4) -> str

Walks the parsed tree and emits canonical bytes. Frontmatter is preserved
byte-for-byte; expression interiors (`{...}`) are never modified; verbatim
elements (`<pre>`, `<textarea>`, `<script>`, `<style>`) preserve their text
content exactly.

The walker is context-aware rather than a Wadler doc tree: each element
picks **inline** mode (single line, text whitespace preserved exactly) or
**block** mode (each child on its own indented line, inter-tag whitespace
freely added) based on whether its children include text, expressions, or
inline-classified child elements.

Hard invariants:

1. Idempotency: `format_source(format_source(x)) == format_source(x)`.
2. Render equivalence (relaxed, Prettier-style): in whitespace-sensitive
   contexts (inline parents, verbatim elements, text-containing parents),
   the formatter never mutates text or inter-element whitespace. In
   whitespace-insensitive contexts (between block siblings in flow
   content), the formatter may add or remove newlines and indentation —
   the rendered HTML remains equivalent under browser parsing.

Known v0 limitations:

- Directives (`:if`, `:for`, `:include`, `slot`) emit before user
  attributes in a fixed order. The parser doesn't preserve their original
  position; idempotency still holds.
- No attribute wrapping when a tag exceeds the print width. All
  attributes stay on the open-tag line.
"""

from __future__ import annotations

from .frontmatter import split as split_frontmatter
from .parser import (
    DoctypeNode,
    ElementNode,
    ExprNode,
    ForClause,
    HtmlCommentNode,
    Node,
    TemplateCommentNode,
    TextNode,
    parse,
)
from .tokenizer import (
    VOID_ELEMENTS,
    AttrExpr,
    Attribute,
    AttrText,
    tokenize,
)
from .whitespace import is_inline, is_verbatim


def format_source(source: str, *, indent_size: int = 4) -> str:
    """Format a `.html` template source string."""
    body_start = _body_offset(source)
    frontmatter_block = source[:body_start]

    _, body = split_frontmatter(source)
    tokens = tokenize(body)
    tree = parse(tokens)

    body_out = _format_root(tree, indent_size=indent_size)
    if not body_out.endswith("\n"):
        body_out += "\n"
    return frontmatter_block + body_out


def _body_offset(source: str) -> int:
    if not source.startswith("---\n"):
        return 0
    i = 4
    while i < len(source):
        end = source.find("\n", i)
        if end == -1:
            return 0
        if source[i:end].strip() == "---":
            return end + 1
        i = end + 1
    return 0


def _format_root(nodes: list[Node], *, indent_size: int) -> str:
    """Format the top-level node sequence (one node per line, no indent)."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, TextNode) and not node.text.strip():
            continue
        parts.append(_format_node(node, indent=0, indent_size=indent_size))
    return "\n".join(parts)


def _format_node(node: Node, *, indent: int, indent_size: int) -> str:
    """Render one node as a string. Caller controls surrounding whitespace."""
    match node:
        case TextNode():
            return node.text
        case ExprNode():
            return "{" + node.code + "}"
        case HtmlCommentNode():
            return f"<!--{node.text}-->"
        case TemplateCommentNode():
            return "{#" + node.text + "#}"
        case DoctypeNode():
            return node.text
        case ElementNode():
            return _format_element(node, indent=indent, indent_size=indent_size)
        case _:
            raise ValueError(f"Unknown node type: {type(node).__name__}")


def _format_element(node: ElementNode, *, indent: int, indent_size: int) -> str:
    open_tag = _format_open_tag(node)

    if node.self_closing or node.tag in VOID_ELEMENTS:
        return open_tag

    close_tag = f"</{node.tag}>"

    if is_verbatim(node.tag):
        # `<script>`/`<style>` bodies are a single opaque text node per the
        # tokenizer's opaque-body rule. `<pre>`/`<textarea>` bodies tokenize
        # normally, so expression nodes can appear — emit every child
        # byte-for-byte preserving original whitespace.
        body = "".join(
            _format_node(c, indent=indent, indent_size=indent_size)
            for c in node.children
        )
        return f"{open_tag}{body}{close_tag}"

    if not node.children:
        return f"{open_tag}{close_tag}"

    if _format_inline(node):
        body = "".join(
            _format_node(c, indent=indent, indent_size=indent_size)
            for c in node.children
        )
        return f"{open_tag}{body}{close_tag}"

    inner_indent = indent + indent_size
    pad = " " * indent
    inner_pad = " " * inner_indent

    parts = [open_tag]
    for child in node.children:
        if isinstance(child, TextNode) and not child.text.strip():
            continue
        parts.append("\n")
        parts.append(inner_pad)
        parts.append(_format_node(child, indent=inner_indent, indent_size=indent_size))
    parts.append("\n")
    parts.append(pad)
    parts.append(close_tag)
    return "".join(parts)


def _format_inline(node: ElementNode) -> bool:
    """Inline mode: children include text content, expressions, or inline elements.

    When True, the formatter renders the element on a single line and
    preserves all text whitespace exactly. When False (block mode),
    children get their own indented lines and inter-tag whitespace is
    inserted freely.
    """
    for c in node.children:
        if isinstance(c, TextNode) and c.text.strip():
            return True
        if isinstance(c, ExprNode):
            return True
        if isinstance(c, ElementNode) and is_inline(c.tag):
            return True
    return False


def _format_open_tag(node: ElementNode) -> str:
    parts: list[str] = ["<", node.tag]

    for piece in _directive_attrs(node):
        parts.append(" ")
        parts.append(piece)

    for attr in node.attrs:
        parts.append(" ")
        parts.append(_format_attribute(attr))

    if node.self_closing:
        parts.append(" />")
    else:
        parts.append(">")
    return "".join(parts)


def _directive_attrs(node: ElementNode) -> list[str]:
    out: list[str] = []
    if node.if_code is not None:
        out.append(f":if={{{node.if_code}}}")
    if node.for_clause is not None:
        out.append(f":for={{{_format_for_clause(node.for_clause)}}}")
    if node.include_path is not None:
        out.append(f':include="{node.include_path}"')
    elif node.include_path_code is not None:
        out.append(f":include={{{node.include_path_code}}}")
    if node.slot_name is not None:
        out.append(f'slot="{node.slot_name}"')
    return out


def _format_for_clause(clause: ForClause) -> str:
    # Prefer the original target source when available so tuple-unpack
    # parens like `(a, b) in xs` survive round-trip — the parser strips
    # them into a flat name list otherwise.
    target = clause.raw_target or (
        clause.targets[0] if len(clause.targets) == 1 else ", ".join(clause.targets)
    )
    return f"{target} in {clause.iter_code}"


def _format_attribute(attr: Attribute) -> str:
    if attr.segments is None:
        return attr.name
    rendered = _format_attr_value(attr.segments)
    return f'{attr.name}="{rendered}"'


def _format_attr_value(segments: list[AttrText | AttrExpr]) -> str:
    out: list[str] = []
    for seg in segments:
        if isinstance(seg, AttrText):
            out.append(seg.text)
        else:
            out.append("{" + seg.code + "}")
    return "".join(out)
