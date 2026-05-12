"""Tree-walking renderer.

Phase 0 scope: interpret a parsed tag tree directly against a context dict,
producing an HTML output string. Phase 5 will replace this interpreter with
an AOT compile-to-Python step; output is byte-equivalent by construction.
"""

from __future__ import annotations

import os
from pathlib import Path

from plain.utils.html import conditional_escape

from . import frontmatter as fm
from .parser import (
    DoctypeNode,
    ElementNode,
    ExprNode,
    HtmlCommentNode,
    Node,
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


class RenderError(Exception):
    pass


def render(path: str | os.PathLike, context: dict | None = None) -> str:
    """Render a `.plain` file from disk."""
    source = Path(path).read_text(encoding="utf-8")
    return render_source(source, context, source_name=str(path))


def render_source(
    source: str, context: dict | None = None, *, source_name: str = "<source>"
) -> str:
    fmdict, body = fm.split(source)
    tokens = tokenize(body)
    tree = parse(tokens)
    scope = _build_scope(fmdict, context or {}, source_name)
    out: list[str] = []
    for node in tree:
        _render_node(node, scope, out)
    return "".join(out)


def _build_scope(fmdict: dict, context: dict, source_name: str) -> dict:
    """Construct the expression-evaluation namespace.

    `imports:` statements run first; caller context wins on name conflict
    because attrs declared by the template are passed there. Python's `eval`
    auto-injects builtins on first use, so we don't seed them explicitly.
    """
    scope: dict = {}
    for stmt in fmdict.get("imports", []) or []:
        try:
            exec(stmt, scope)  # noqa: S102 — frontmatter is trusted author input
        except Exception as e:
            raise RenderError(
                f"Failed to execute import {stmt!r} in {source_name}: {e}"
            ) from e
    scope.update(context)
    return scope


def _render_node(node: Node, scope: dict, out: list[str]) -> None:
    match node:
        case TextNode():
            out.append(node.text)
        case ExprNode():
            out.append(_escape_to_str(_eval(node.code, scope)))
        case HtmlCommentNode():
            out.append(f"<!--{node.text}-->")
        case DoctypeNode():
            out.append(node.text)
        case ElementNode():
            _render_element(node, scope, out)
        case _:
            raise RenderError(f"Unknown node type: {type(node).__name__}")


def _render_element(node: ElementNode, scope: dict, out: list[str]) -> None:
    if node.if_code is not None and not _eval(node.if_code, scope):
        return

    if node.for_clause is None:
        _emit_element(node, scope, out)
        return

    iterable = _eval(node.for_clause.iter_code, scope)
    names = node.for_clause.targets
    for item in iterable:
        inner = dict(scope)
        _bind_targets(inner, names, item)
        _emit_element(node, inner, out)


def _emit_element(node: ElementNode, scope: dict, out: list[str]) -> None:
    if node.tag == "template":
        # `<template>` without `:include` is a transparent fragment.
        for child in node.children:
            _render_node(child, scope, out)
        return

    out.append("<")
    out.append(node.tag)
    for attr in node.attrs:
        rendered = _render_attribute(attr, scope)
        if rendered is not None:
            out.append(rendered)

    if node.self_closing or node.tag in VOID_ELEMENTS:
        out.append(">")
        return
    out.append(">")
    for child in node.children:
        _render_node(child, scope, out)
    out.append("</")
    out.append(node.tag)
    out.append(">")


def _render_attribute(attr: Attribute, scope: dict) -> str | None:
    if attr.segments is None:
        return f" {attr.name}"

    # `name={expr}` — single expression governs boolean / value rendering.
    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        value = _eval(attr.segments[0].code, scope)
        if value is False or value is None:
            return None
        if value is True:
            return f" {attr.name}"
        return f' {attr.name}="{_escape_to_str(value)}"'

    parts: list[str] = []
    for seg in attr.segments:
        match seg:
            case AttrText():
                parts.append(seg.text)
            case AttrExpr():
                parts.append(_escape_to_str(_eval(seg.code, scope)))
    return f' {attr.name}="{"".join(parts)}"'


def _escape_to_str(value: object) -> str:
    """Render a value to an HTML-safe string, treating `None` as empty."""
    if value is None:
        return ""
    return str(conditional_escape(value))


def _eval(code: str, scope: dict) -> object:
    try:
        return eval(code, scope)  # noqa: S307 — Phase 0 interpreter
    except Exception as e:
        raise RenderError(f"Error evaluating {code!r}: {e}") from e


def _bind_targets(scope: dict, names: list[str], item: object) -> None:
    """Bind one item into the scope under one or more names."""
    if len(names) == 1:
        scope[names[0]] = item
        return
    values = list(item)
    if len(values) != len(names):
        raise RenderError(f"Cannot unpack {len(values)} values into {len(names)} names")
    for n, v in zip(names, values, strict=True):
        scope[n] = v
