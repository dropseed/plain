"""Tag tree builder.

Consumes the tokenizer's flat stream and produces a tree of nodes. Lifts
`:if` / `:for` directive attributes onto their host element so the renderer
doesn't have to rediscover them.

Out of scope for Phase 0: `:include` resolution, `:as` scoped slot binding,
slot composition, and full source-position propagation through every error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tokenizer import (
    VOID_ELEMENTS,
    AttrExpr,
    Attribute,
    AttrText,
    DoctypeToken,
    EndTagToken,
    ExprToken,
    HtmlCommentToken,
    StartTagToken,
    TemplateCommentToken,
    TextToken,
    Token,
)


class ParseError(Exception):
    pass


@dataclass
class ForClause:
    """A pre-parsed `target in iterable` directive value."""

    targets: list[str]
    iter_code: str
    raw_target: str = ""


@dataclass
class ElementNode:
    tag: str
    attrs: list[Attribute]
    children: list = field(default_factory=list)
    self_closing: bool = False
    if_code: str | None = None
    for_clause: ForClause | None = None
    include_path: str | None = None  # `:include="..."` literal path
    include_path_code: str | None = None  # `:include={expr}` dynamic path
    slot_name: str | None = None  # `slot="..."` routing attribute


@dataclass
class TextNode:
    text: str


@dataclass
class ExprNode:
    code: str


@dataclass
class HtmlCommentNode:
    text: str


@dataclass
class TemplateCommentNode:
    text: str


@dataclass
class DoctypeNode:
    text: str


Node = (
    ElementNode
    | TextNode
    | ExprNode
    | HtmlCommentNode
    | TemplateCommentNode
    | DoctypeNode
)


def parse(tokens: list[Token]) -> list[Node]:
    root_children: list[Node] = []
    stack: list[ElementNode] = []

    def parent_children() -> list[Node]:
        return stack[-1].children if stack else root_children

    for tok in tokens:
        match tok:
            case TextToken():
                parent_children().append(TextNode(tok.text))
            case ExprToken():
                parent_children().append(ExprNode(tok.code))
            case HtmlCommentToken():
                parent_children().append(HtmlCommentNode(tok.text))
            case TemplateCommentToken():
                parent_children().append(TemplateCommentNode(tok.text))
            case DoctypeToken():
                parent_children().append(DoctypeNode(tok.text))
            case StartTagToken():
                node = _make_element(tok)
                parent_children().append(node)
                is_void = node.tag in VOID_ELEMENTS
                if not (node.self_closing or is_void):
                    stack.append(node)
            case EndTagToken():
                if not stack:
                    raise ParseError(
                        f"Unexpected </{tok.name}> at offset {tok.offset}: no open element"
                    )
                top = stack[-1]
                if top.tag != tok.name:
                    raise ParseError(
                        f"Mismatched tag: expected </{top.tag}> but got </{tok.name}> "
                        f"at offset {tok.offset}"
                    )
                stack.pop()
            case _:
                raise ParseError(f"Unknown token: {tok!r}")

    if stack:
        unclosed = ", ".join(f"<{el.tag}>" for el in stack)
        raise ParseError(f"Unclosed elements: {unclosed}")

    return root_children


def _make_element(tok: StartTagToken) -> ElementNode:
    attrs: list[Attribute] = []
    if_code: str | None = None
    for_clause: ForClause | None = None
    include_path: str | None = None
    include_path_code: str | None = None
    slot_name: str | None = None

    for attr in tok.attrs:
        if attr.name == ":if":
            if_code = _expect_single_expr(attr)
        elif attr.name == ":for":
            for_clause = _parse_for_clause(_expect_single_expr(attr))
        elif attr.name == ":include":
            if tok.name != "template":
                raise ParseError(
                    f":include must be on a <template> element, not <{tok.name}>"
                )
            include_path, include_path_code = _split_include_value(attr)
        elif attr.name == "slot":
            slot_name = _expect_single_text(attr)
        elif attr.name.startswith(":"):
            # Reserved for future directives (`:as`). Phase 0 lets them through
            # silently so prototype templates can be written against the spec
            # ahead of implementation.
            continue
        else:
            attrs.append(attr)

    return ElementNode(
        tag=tok.name,
        attrs=attrs,
        self_closing=tok.self_closing,
        if_code=if_code,
        for_clause=for_clause,
        include_path=include_path,
        include_path_code=include_path_code,
        slot_name=slot_name,
    )


def _expect_single_text(attr: Attribute) -> str:
    if attr.segments is None or len(attr.segments) != 1:
        raise ParseError(f"{attr.name} must be a literal string value")
    seg = attr.segments[0]
    if not isinstance(seg, AttrText):
        raise ParseError(f"{attr.name} must be a literal string value")
    return seg.text


def _split_include_value(attr: Attribute) -> tuple[str | None, str | None]:
    """Resolve `:include="path"` vs `:include={expr}`.

    Returns (literal_path, expression_code). Exactly one of the two will be
    non-None; the renderer picks the active branch.
    """
    if attr.segments is None or len(attr.segments) != 1:
        raise ParseError(":include must be a single value")
    seg = attr.segments[0]
    if isinstance(seg, AttrText):
        return seg.text, None
    if isinstance(seg, AttrExpr):
        return None, seg.code
    raise ParseError(":include must be a literal string or a single {expression}")


def _expect_single_expr(attr: Attribute) -> str:
    if attr.segments is None or len(attr.segments) != 1:
        raise ParseError(f"Directive {attr.name} must be a single {{expression}}")
    seg = attr.segments[0]
    if not isinstance(seg, AttrExpr):
        raise ParseError(f"Directive {attr.name} must be a single {{expression}}")
    return seg.code


def _parse_for_clause(clause: str) -> ForClause:
    """Split `target in iterable`, returning typed names plus the iterable
    expression.

    Splits on the first top-level ` in ` keyword. Handles tuple targets like
    `(i, item) in enumerate(xs)` via parenthesis tracking.
    """
    depth = 0
    i = 0
    n = len(clause)
    while i < n:
        c = clause[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and clause.startswith(" in ", i):
            target = clause[:i].strip()
            iter_code = clause[i + 4 :].strip()
            return ForClause(
                targets=_parse_target_names(target),
                iter_code=iter_code,
                raw_target=target,
            )
        i += 1
    raise ParseError(f":for clause missing ' in ' separator: {clause!r}")


def _parse_target_names(target: str) -> list[str]:
    """Extract one or more names from a `:for` target.

    Single name → one-element list. Tuple unpack (optionally parenthesized) →
    list of names in order.
    """
    t = target.strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    if "," in t:
        return [n.strip() for n in t.split(",") if n.strip()]
    return [t]
