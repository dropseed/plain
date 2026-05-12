"""Tree-walking renderer.

Phase 0 scope: interpret a parsed tag tree directly against a context dict,
producing an HTML output string. No compile-to-Python step yet — Phase 5
replaces this interpreter with an AOT compiler that emits Python source.

The interpreter is sufficient for parity verification because the output of
"interpret tree" and "execute compiled render() function" is byte-equivalent
by construction.
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path

from . import frontmatter as fm
from .escape import escape_attr, escape_html
from .parser import (
    DoctypeNode,
    ElementNode,
    ExprNode,
    HtmlCommentNode,
    Node,
    TextNode,
    parse,
)
from .tokenizer import VOID_ELEMENTS, tokenize


class RenderError(Exception):
    pass


def render(path: str | os.PathLike, context: dict | None = None) -> str:
    """Render a .plain file from disk."""
    source = Path(path).read_text()
    return render_source(source, context, source_name=str(path))


def render_source(
    source: str, context: dict | None = None, *, source_name: str = "<source>"
) -> str:
    """Render a .plain source string."""
    fmdict, body, _ = fm.split(source)
    tokens = tokenize(body)
    tree = parse(tokens)
    scope = _build_scope(fmdict, context or {}, source_name)
    out: list[str] = []
    for node in tree:
        _render_node(node, scope, out)
    return "".join(out)


def _build_scope(fmdict: dict, context: dict, source_name: str) -> dict:
    """Construct the expression-evaluation namespace.

    Order: builtins → executed `imports:` → caller's context. Caller context
    wins because attrs declared by the template are passed there.
    """
    scope: dict = {}
    scope.update(vars(builtins))
    for stmt in fmdict.get("imports", []) or []:
        try:
            exec(stmt, scope)  # noqa: S102 — frontmatter is trusted template author input
        except Exception as e:
            raise RenderError(
                f"Failed to execute import {stmt!r} in {source_name}: {e}"
            ) from e
    scope.update(context)
    return scope


def _render_node(node: Node, scope: dict, out: list[str]) -> None:
    if isinstance(node, TextNode):
        out.append(node.text)
    elif isinstance(node, ExprNode):
        value = _eval(node.code, scope)
        out.append(escape_html(value))
    elif isinstance(node, HtmlCommentNode):
        out.append(f"<!--{node.text}-->")
    elif isinstance(node, DoctypeNode):
        out.append(node.text)
    elif isinstance(node, ElementNode):
        _render_element(node, scope, out)
    else:
        raise RenderError(f"Unknown node type: {type(node).__name__}")


def _render_element(node: ElementNode, scope: dict, out: list[str]) -> None:
    if node.if_code is not None:
        if not _eval(node.if_code, scope):
            return

    if node.for_iter is not None:
        iterable = _eval(node.for_iter, scope)
        target = node.for_target
        for item in iterable:
            inner = dict(scope)
            _bind_target(inner, target, item)
            _emit_element(node, inner, out)
        return

    _emit_element(node, scope, out)


def _emit_element(node: ElementNode, scope: dict, out: list[str]) -> None:
    if node.is_template_fragment:
        # <template> with no :include is a transparent fragment.
        for child in node.children:
            _render_node(child, scope, out)
        return

    out.append("<")
    out.append(node.tag)
    for name, segments, is_expr in node.attrs:
        rendered = _render_attribute(name, segments, is_expr, scope)
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


def _render_attribute(
    name: str, segments: list | None, is_expr: bool, scope: dict
) -> str | None:
    if segments is None:
        # Boolean attribute with no value.
        return f" {name}"

    if is_expr:
        # Single {expr} value — boolean coercion rules apply.
        kind, code = segments[0]
        assert kind == "expr"
        value = _eval(code, scope)
        if value is False or value is None:
            return None
        if value is True:
            return f" {name}"
        return f' {name}="{escape_attr(value)}"'

    # String value, possibly with embedded {expr} segments.
    parts: list[str] = []
    for kind, payload in segments:
        if kind == "text":
            parts.append(payload)
        elif kind == "expr":
            parts.append(escape_attr(_eval(payload, scope)))
        else:  # pragma: no cover
            raise RenderError(f"Unknown attr segment kind: {kind}")
    value = "".join(parts)
    return f' {name}="{value}"'


def _eval(code: str, scope: dict) -> object:
    try:
        return eval(code, scope)  # noqa: S307 — Phase 0 interpreter
    except Exception as e:
        raise RenderError(f"Error evaluating {code!r}: {e}") from e


def _bind_target(scope: dict, target: str, item: object) -> None:
    """Bind an iteration target into the scope. Supports simple names and
    parenthesized tuple unpacks like ``(i, x)`` or ``i, x``.
    """
    t = target.strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    if "," in t:
        names = [n.strip() for n in t.split(",") if n.strip()]
        values = list(item)
        if len(names) != len(values):
            raise RenderError(
                f"Cannot unpack {len(values)} values into {len(names)} names: {target!r}"
            )
        for n, v in zip(names, values, strict=False):
            scope[n] = v
    else:
        scope[t] = item
