"""Formatter for `.html` templates (Phase 9.5).

Public API:

    format_source(source: str, *, indent_size: int = 4) -> str

Walks the parsed tree and emits canonical bytes. Frontmatter values are
preserved byte-for-byte; only the **top-level key order** is canonicalized
to `imports → attrs → slots → (others, original order)`. Expression
interiors (`{...}`) are never modified; verbatim elements (`<pre>`,
`<textarea>`, `<script>`, `<style>`) preserve their text content exactly.

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

Deliberate canonical-form choices (not bugs):

- Directives (`:if`, `:for`, `:include`, `slot`, plus reserved `:`-prefixed
  attrs like `:as`) emit before user attributes in a fixed order, not in
  the author's original position. Rationale: in plain.html, directives are
  control flow (the engine acts on them), distinct from data attributes.
  Putting them first makes them scan-readable like an if-statement header
  and groups them away from HTML output attributes.
"""

from __future__ import annotations

import re

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

DEFAULT_WIDTH = 88

# Top-level frontmatter keys, in the order the formatter emits them. Any
# key not listed keeps its original relative position (stable-sorted) and
# sorts after the canonical block.
_CANONICAL_FRONTMATTER_KEYS = ("imports", "attrs", "slots")


def format_source(
    source: str, *, indent_size: int = 4, width: int = DEFAULT_WIDTH
) -> str:
    """Format a `.html` template source string."""
    body_start = _body_offset(source)
    frontmatter_block = _format_frontmatter(source[:body_start])

    _, body = split_frontmatter(source)
    tokens = tokenize(body)
    tree = parse(tokens)

    body_out = _format_root(tree, indent_size=indent_size, width=width)
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


def _format_frontmatter(block: str) -> str:
    """Canonicalize the order of top-level keys in a `---`-delimited block.

    Values are preserved byte-for-byte. Only the order of the top-level
    sections (each `key:` line and its indented continuation) is changed.
    Keys not in the canonical list keep their relative position.
    """
    match = re.match(r"\A---\n(.*?\n)---\n", block, re.DOTALL)
    if match is None:
        return block

    inner = match.group(1)
    sections, leading = _parse_frontmatter_sections(inner)
    if not sections:
        return block

    reordered = sorted(
        enumerate(sections),
        key=lambda x: (_canonical_index(x[1][0]), x[0]),
    )
    new_inner = leading + "".join(text for _, (_, text) in reordered)
    if not new_inner.endswith("\n"):
        new_inner += "\n"
    return f"---\n{new_inner}---\n"


def _parse_frontmatter_sections(inner: str) -> tuple[list[tuple[str, str]], str]:
    """Split frontmatter text into (key, raw-block) pairs.

    Each section keeps its original `key:` line, its indented continuation,
    and any trailing blank lines that belong to it. Returns `(sections,
    leading_blanks)` so leading blank lines before the first key don't get
    swallowed.
    """
    lines = inner.split("\n")
    # `split` on a trailing `\n` produces an empty final element; trim it
    # so we don't emit a phantom blank.
    if lines and lines[-1] == "":
        lines.pop()

    sections: list[tuple[str, list[str]]] = []
    leading: list[str] = []
    i = 0
    n = len(lines)
    while i < n and lines[i] == "":
        leading.append(lines[i])
        i += 1

    while i < n:
        line = lines[i]
        match = re.match(r"^([A-Za-z_][\w-]*)\s*:", line)
        if not match:
            # Unrecognized shape (a stray comment, say). Attach to the
            # previous section so it travels with it, or to `leading` if
            # nothing's been seen yet.
            if sections:
                sections[-1][1].append(line)
            else:
                leading.append(line)
            i += 1
            continue

        key = match.group(1)
        block_lines: list[str] = [line]
        i += 1
        while i < n:
            nxt = lines[i]
            if nxt == "" or nxt.startswith(" ") or nxt.startswith("\t"):
                block_lines.append(nxt)
                i += 1
                continue
            break
        sections.append((key, block_lines))

    pairs = [(key, "\n".join(block_lines) + "\n") for key, block_lines in sections]
    leading_text = ("\n".join(leading) + "\n") if leading else ""
    return pairs, leading_text


def _canonical_index(key: str) -> int:
    if key in _CANONICAL_FRONTMATTER_KEYS:
        return _CANONICAL_FRONTMATTER_KEYS.index(key)
    return len(_CANONICAL_FRONTMATTER_KEYS)


def _format_root(nodes: list[Node], *, indent_size: int, width: int) -> str:
    """Format the top-level node sequence (one node per line, no indent)."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, TextNode) and not node.text.strip():
            continue
        parts.append(_format_node(node, indent=0, indent_size=indent_size, width=width))
    return "\n".join(parts)


def _format_node(node: Node, *, indent: int, indent_size: int, width: int) -> str:
    """Render one node as a string. Caller controls surrounding whitespace."""
    match node:
        case TextNode():
            # Re-encode literal braces — the tokenizer decoded `{{`/`}}` into
            # single `{`/`}` on the way in, so on the way out we restore the
            # escape or the re-parsed bytes become a live `{...}` expression.
            # The script/style path below bypasses this; their bodies are
            # opaque and the tokenizer never decoded them.
            return node.text.replace("{", "{{").replace("}", "}}")
        case ExprNode():
            return "{" + node.code + "}"
        case HtmlCommentNode():
            return f"<!--{node.text}-->"
        case TemplateCommentNode():
            return "{#" + node.text + "#}"
        case DoctypeNode():
            return node.text
        case ElementNode():
            return _format_element(
                node, indent=indent, indent_size=indent_size, width=width
            )
        case _:
            raise ValueError(f"Unknown node type: {type(node).__name__}")


def _format_element(
    node: ElementNode, *, indent: int, indent_size: int, width: int
) -> str:
    open_tag = _format_open_tag(
        node, indent=indent, indent_size=indent_size, width=width
    )

    if node.self_closing or node.tag in VOID_ELEMENTS:
        return open_tag

    close_tag = f"</{node.tag}>"

    if is_verbatim(node.tag):
        if node.tag in ("script", "style"):
            # Opaque body: tokenizer captured the full text verbatim without
            # decoding brace escapes. Emit byte-for-byte; do not re-escape.
            body = "".join(c.text for c in node.children if isinstance(c, TextNode))
        else:
            # `<pre>`/`<textarea>` bodies tokenize normally — text and
            # expression nodes both appear, brace escapes were decoded on
            # the way in, and `_format_node` re-encodes them on the way out.
            body = "".join(
                _format_node(c, indent=indent, indent_size=indent_size, width=width)
                for c in node.children
            )
        return f"{open_tag}{body}{close_tag}"

    if not node.children:
        return f"{open_tag}{close_tag}"

    if _format_inline(node):
        body = "".join(
            _format_node(c, indent=indent, indent_size=indent_size, width=width)
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
        parts.append(
            _format_node(
                child, indent=inner_indent, indent_size=indent_size, width=width
            )
        )
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


def _format_open_tag(
    node: ElementNode, *, indent: int, indent_size: int, width: int
) -> str:
    # Per the HTML5 spec, void elements (img, br, hr, input, …) always
    # use the bare `<tag>` form. The trailing `/` is "permitted but has
    # no effect" — a legacy XHTML accommodation we don't emit. Drop the
    # source's self-closing flag for void tags so output is canonical.
    self_closing = node.self_closing and node.tag not in VOID_ELEMENTS

    attrs = _directive_attrs(node) + [_format_attribute(a) for a in node.attrs]
    flat = _open_tag_flat(node.tag, attrs, self_closing=self_closing)

    if not attrs or indent + len(flat) <= width:
        return flat

    return _open_tag_wrapped(
        node.tag,
        attrs,
        self_closing=self_closing,
        indent=indent,
        indent_size=indent_size,
    )


def _open_tag_flat(tag: str, attrs: list[str], *, self_closing: bool) -> str:
    parts: list[str] = ["<", tag]
    for attr in attrs:
        parts.append(" ")
        parts.append(attr)
    parts.append(" />" if self_closing else ">")
    return "".join(parts)


def _open_tag_wrapped(
    tag: str,
    attrs: list[str],
    *,
    self_closing: bool,
    indent: int,
    indent_size: int,
) -> str:
    inner_pad = " " * (indent + indent_size)
    pad = " " * indent
    parts: list[str] = ["<", tag, "\n"]
    for attr in attrs:
        parts.append(inner_pad)
        parts.append(attr)
        parts.append("\n")
    parts.append(pad)
    parts.append("/>" if self_closing else ">")
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
    for attr in node.reserved_directives:
        out.append(_format_attribute(attr))
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
    # A value that's a single `{expr}` emits unquoted — matches how authors
    # write `:if={ok}` or `class={x}` and is what the recognized directives
    # already canonicalize to.
    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        return f"{attr.name}={{{attr.segments[0].code}}}"
    # HTML5 boolean attribute: `disabled="disabled"` collapses to `disabled`.
    if (
        len(attr.segments) == 1
        and isinstance(attr.segments[0], AttrText)
        and attr.segments[0].text == attr.name
    ):
        return attr.name
    rendered = _format_attr_value(attr.segments)
    quote = '"' if '"' not in rendered or "'" in rendered else "'"
    return f"{attr.name}={quote}{rendered}{quote}"


def _format_attr_value(segments: list[AttrText | AttrExpr]) -> str:
    out: list[str] = []
    for seg in segments:
        if isinstance(seg, AttrText):
            out.append(seg.text)
        else:
            out.append("{" + seg.code + "}")
    return "".join(out)
