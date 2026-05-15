"""Tag tree builder.

Consumes the tokenizer's flat stream and produces a tree of nodes. Lifts
the recognized directive attributes (`:if`, `:elif`, `:else`, `:for`,
`:slot`) onto their host `ElementNode` so the compiler doesn't have to
rediscover them. Any other `:`-prefixed attribute is kept under
`reserved_directives` so the formatter can round-trip it.

A PascalCase tag is a component invocation: the parser looks it up in the
`components:` map and sets `include_path`, reusing the static-include
compile backend.
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
    """A pre-parsed `target in iterable` directive value.

    `filter_code` holds any trailing comprehension-style `if` filters
    (`for x in xs if cond`). It's the raw Python source of everything
    after the first top-level ` if `; `None` when no filter is present.
    """

    targets: list[str]
    iter_code: str
    raw_target: str = ""
    filter_code: str | None = None


@dataclass
class ElementNode:
    tag: str
    attrs: list[Attribute]
    children: list = field(default_factory=list)
    self_closing: bool = False
    if_code: str | None = None
    elif_code: str | None = None  # `:elif={expr}` — chains after a `:if`
    is_else: bool = False  # `:else` — bare directive, ends a chain
    for_clause: ForClause | None = None
    include_path: str | None = None  # component path — set for PascalCase tags
    slot_name: str | None = None  # `:slot="..."` routing
    reserved_directives: list[Attribute] = field(default_factory=list)
    # `:as` and any other `:`-prefixed attr the engine doesn't recognize.
    # Held on the node so the formatter can round-trip them; the renderer
    # ignores them.
    offset: int = 0  # body offset of the start tag, for source mapping


@dataclass
class TextNode:
    text: str
    offset: int = 0


@dataclass
class ExprNode:
    code: str
    offset: int = 0


@dataclass
class HtmlCommentNode:
    text: str
    offset: int = 0


@dataclass
class TemplateCommentNode:
    text: str
    offset: int = 0


@dataclass
class DoctypeNode:
    text: str
    offset: int = 0


Node = (
    ElementNode
    | TextNode
    | ExprNode
    | HtmlCommentNode
    | TemplateCommentNode
    | DoctypeNode
)


def parse(
    tokens: list[Token], *, components: dict[str, str] | None = None
) -> list[Node]:
    root_children: list[Node] = []
    stack: list[ElementNode] = []
    components = components or {}

    def parent_children() -> list[Node]:
        return stack[-1].children if stack else root_children

    for tok in tokens:
        match tok:
            case TextToken():
                parent_children().append(TextNode(tok.text, offset=tok.offset))
            case ExprToken():
                parent_children().append(ExprNode(tok.code, offset=tok.offset))
            case HtmlCommentToken():
                parent_children().append(HtmlCommentNode(tok.text, offset=tok.offset))
            case TemplateCommentToken():
                parent_children().append(
                    TemplateCommentNode(tok.text, offset=tok.offset)
                )
            case DoctypeToken():
                parent_children().append(DoctypeNode(tok.text, offset=tok.offset))
            case StartTagToken():
                node = _make_element(tok, components)
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

    _validate_conditional_chains(root_children)
    return root_children


def _validate_conditional_chains(nodes: list[Node]) -> None:
    """Check `:if`/`:elif`/`:else` ordering across every children list.

    An element carrying `:elif` or `:else` must be immediately preceded —
    skipping whitespace-only text and comment nodes — by an element
    carrying `:if` or `:elif`. Recurses into every element's children.
    """
    prev: ElementNode | None = None
    for node in nodes:
        if isinstance(node, TextNode) and not node.text.strip():
            continue
        if isinstance(node, HtmlCommentNode | TemplateCommentNode):
            continue
        if isinstance(node, ElementNode):
            if node.elif_code is not None:
                if prev is None or (prev.if_code is None and prev.elif_code is None):
                    raise ParseError(
                        f":elif at offset {node.offset} must directly follow a "
                        f":if or :elif element"
                    )
            elif node.is_else:
                if prev is None or (prev.if_code is None and prev.elif_code is None):
                    raise ParseError(
                        f":else at offset {node.offset} must directly follow a "
                        f":if or :elif element"
                    )
            _validate_conditional_chains(node.children)
            prev = node
        else:
            prev = None


def _make_element(tok: StartTagToken, components: dict[str, str]) -> ElementNode:
    attrs: list[Attribute] = []
    reserved_directives: list[Attribute] = []
    if_code: str | None = None
    elif_code: str | None = None
    is_else: bool = False
    for_clause: ForClause | None = None
    slot_name: str | None = None

    for attr in tok.attrs:
        if attr.name == ":if":
            if_code = _expect_single_expr(attr)
        elif attr.name == ":elif":
            elif_code = _expect_single_expr(attr)
        elif attr.name == ":else":
            if attr.segments is not None:
                raise ParseError(":else is a bare directive — it takes no value")
            is_else = True
        elif attr.name == ":for":
            for_clause = _parse_for_clause(_expect_single_expr(attr))
        elif attr.name == ":slot":
            slot_name = _expect_single_text(attr)
        elif attr.name.startswith(":"):
            # Reserved directives like `:as` that the engine doesn't act on yet.
            # Held so the formatter can round-trip them without erasing author code.
            reserved_directives.append(attr)
        else:
            attrs.append(attr)

    # A conditional directive and `:for` on the same element is ambiguous —
    # the author should gate a loop with `<template :if>` or filter the
    # `:for` clause itself.
    if for_clause is not None and (
        if_code is not None or elif_code is not None or is_else
    ):
        raise ParseError(
            f"`:for` and a conditional directive on the same <{tok.name}> at "
            f"offset {tok.offset} — gate the loop with a `<template :if>` "
            f"wrapper, or filter with `:for={{x in y if cond}}`"
        )

    # A PascalCase tag is a component invocation — it must be declared in
    # the `components:` frontmatter so its path is statically known.
    include_path: str | None = None
    if _is_component_tag(tok.name):
        mapped = components.get(tok.name)
        if mapped is None:
            raise ParseError(
                f"unknown component `<{tok.name}>` — add it to the "
                f"`components:` frontmatter"
            )
        include_path = mapped

    return ElementNode(
        tag=tok.name,
        attrs=attrs,
        self_closing=tok.self_closing,
        if_code=if_code,
        elif_code=elif_code,
        is_else=is_else,
        for_clause=for_clause,
        include_path=include_path,
        slot_name=slot_name,
        reserved_directives=reserved_directives,
        offset=tok.offset,
    )


def _is_component_tag(tag: str) -> bool:
    """A component tag is PascalCase: starts with an uppercase letter."""
    return bool(tag) and tag[0].isupper()


def _expect_single_text(attr: Attribute) -> str:
    if attr.segments is None or len(attr.segments) != 1:
        raise ParseError(f"{attr.name} must be a literal string value")
    seg = attr.segments[0]
    if not isinstance(seg, AttrText):
        raise ParseError(f"{attr.name} must be a literal string value")
    return seg.text


def _expect_single_expr(attr: Attribute) -> str:
    if attr.segments is None or len(attr.segments) != 1:
        raise ParseError(f"Directive {attr.name} must be a single {{expression}}")
    seg = attr.segments[0]
    if not isinstance(seg, AttrExpr):
        raise ParseError(f"Directive {attr.name} must be a single {{expression}}")
    return seg.code


def _parse_for_clause(clause: str) -> ForClause:
    """Split `target in iterable [if filter ...]`, returning typed names,
    the iterable expression, and any trailing comprehension `if` filters.

    Splits on the first top-level ` in ` keyword. Handles tuple targets like
    `(i, item) in enumerate(xs)` via parenthesis tracking. After the
    iterable, a top-level ` if ` begins the filter — everything from there
    is `filter_code`. A second top-level ` for ` (a nested loop) is
    rejected.
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
            rest = clause[i + 4 :].strip()
            iter_code, filter_code = _split_for_filter(rest)
            return ForClause(
                targets=_parse_target_names(target),
                iter_code=iter_code,
                raw_target=target,
                filter_code=filter_code,
            )
        i += 1
    raise ParseError(f":for clause missing ' in ' separator: {clause!r}")


def _split_for_filter(rest: str) -> tuple[str, str | None]:
    """Split the post-`in` portion into (iterable, filter | None).

    Scans for top-level ` if ` keywords — everything before the first is
    the iterable. Each ` if ` opens a comprehension filter; multiple
    filters (`for x in xs if a if b`) combine into one `filter_code`
    string joined with `and` (the semantics a comprehension gives them).
    A top-level ` for ` (a second loop clause) is a `ParseError`.
    """
    depth = 0
    i = 0
    n = len(rest)
    if_positions: list[int] = []
    while i < n:
        c = rest[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and rest.startswith(" for ", i):
            raise ParseError(
                f":for accepts only one `for` clause — nested loops are not "
                f"allowed; use a nested `<template :for>` instead: {rest!r}"
            )
        elif depth == 0 and rest.startswith(" if ", i):
            if_positions.append(i)
        i += 1
    if not if_positions:
        return rest, None

    iter_code = rest[: if_positions[0]].strip()
    # Slice out each filter expression (the text between successive `if`
    # keyword boundaries). `+ 4` skips past the ` if ` token.
    filters: list[str] = []
    bounds = if_positions + [n]
    for idx, start in enumerate(if_positions):
        filt = rest[start + 4 : bounds[idx + 1]].strip()
        # Parenthesize each filter so combining with `and` is unambiguous.
        filters.append(f"({filt})" if len(if_positions) > 1 else filt)
    filter_code = " and ".join(filters)
    return iter_code, filter_code


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
