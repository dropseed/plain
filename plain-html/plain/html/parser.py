"""Tag tree builder.

Phase 0 scope: consume the tokenizer's flat stream and build a nested tree of
nodes. Lift directive attributes (`:if`, `:for`) onto their host element so the
renderer doesn't have to rediscover them. `<template>` elements are recognized
as transparent fragments.

Out of scope for Phase 0:
- `:include` resolution (no cross-template invocation yet)
- `:as` scoped slot binding
- Slot composition / `slot="name"` routing
- Detailed source-position propagation through every error
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tokenizer import (
    VOID_ELEMENTS,
    DoctypeToken,
    EndTagToken,
    ExprToken,
    HtmlCommentToken,
    StartTagToken,
    TextToken,
    Token,
)


class ParseError(Exception):
    pass


@dataclass
class ElementNode:
    tag: str
    attrs: list[tuple[str, list | None, bool]]
    children: list = field(default_factory=list)
    self_closing: bool = False
    if_code: str | None = None
    for_target: str | None = None
    for_iter: str | None = None
    is_template_fragment: bool = False  # <template> with no :include


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
class DoctypeNode:
    text: str


Node = ElementNode | TextNode | ExprNode | HtmlCommentNode | DoctypeNode


def parse(tokens: list[Token]) -> list[Node]:
    """Build a tree from tokens. Returns the top-level node list."""
    root_children: list[Node] = []
    stack: list[ElementNode] = []

    def parent_children() -> list[Node]:
        return stack[-1].children if stack else root_children

    for tok in tokens:
        if isinstance(tok, TextToken):
            parent_children().append(TextNode(tok.text))
        elif isinstance(tok, ExprToken):
            parent_children().append(ExprNode(tok.code))
        elif isinstance(tok, HtmlCommentToken):
            parent_children().append(HtmlCommentNode(tok.text))
        elif isinstance(tok, DoctypeToken):
            parent_children().append(DoctypeNode(tok.text))
        elif isinstance(tok, StartTagToken):
            node = _make_element(tok)
            parent_children().append(node)
            is_void = node.tag in VOID_ELEMENTS
            if not (node.self_closing or is_void):
                stack.append(node)
        elif isinstance(tok, EndTagToken):
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
        else:
            raise ParseError(f"Unknown token: {tok!r}")

    if stack:
        unclosed = ", ".join(f"<{el.tag}>" for el in stack)
        raise ParseError(f"Unclosed elements: {unclosed}")

    return root_children


def _make_element(tok: StartTagToken) -> ElementNode:
    attrs: list[tuple[str, list | None, bool]] = []
    if_code: str | None = None
    for_target: str | None = None
    for_iter: str | None = None

    for name, segments, is_expr in tok.attrs:
        if name == ":if":
            if_code = _expect_single_expr(name, segments)
        elif name == ":for":
            target, iter_code = _parse_for_clause(_expect_single_expr(name, segments))
            for_target = target
            for_iter = iter_code
        elif name.startswith(":"):
            # Reserved for future directives (:include, :as). Phase 0 ignores
            # them rather than failing — keeps the prototype permissive.
            pass
        else:
            attrs.append((name, segments, is_expr))

    is_template_fragment = tok.name == "template"

    return ElementNode(
        tag=tok.name,
        attrs=attrs,
        self_closing=tok.self_closing,
        if_code=if_code,
        for_target=for_target,
        for_iter=for_iter,
        is_template_fragment=is_template_fragment,
    )


def _expect_single_expr(directive: str, segments: list | None) -> str:
    if not segments:
        raise ParseError(f"Directive {directive} requires a value")
    if len(segments) != 1 or segments[0][0] != "expr":
        raise ParseError(f"Directive {directive} must be a single {{expression}}")
    return segments[0][1]


def _parse_for_clause(clause: str) -> tuple[str, str]:
    """Split `target in iterable` into (target_code, iterable_code).

    Splits on the first top-level ' in ' keyword. Handles tuple targets like
    `(i, item) in enumerate(xs)` by relying on parenthesis tracking.
    """
    # Walk char-by-char to find the unparenthesized " in " separator.
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
            return target, iter_code
        i += 1
    raise ParseError(f":for clause missing ' in ' separator: {clause!r}")
