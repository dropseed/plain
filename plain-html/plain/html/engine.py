"""Tree-walking renderer.

Phase 0 scope: interpret a parsed tag tree directly against a context dict,
producing an HTML output string. Phase 5 will replace this interpreter with
an AOT compile-to-Python step; output is byte-equivalent by construction.
"""

from __future__ import annotations

import os
from pathlib import Path

from plain.utils.html import conditional_escape
from plain.utils.safestring import SafeString, mark_safe

from . import frontmatter as fm
from .globals import all_globals
from .loader import find_template
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
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    return render_source(source, context, source_path=path)


def render_source(
    source: str,
    context: dict | None = None,
    *,
    source_path: Path | None = None,
    root_context: dict | None = None,
) -> str:
    fmdict, body = fm.split(source)
    tokens = tokenize(body)
    tree = parse(tokens)
    ctx = dict(context or {})
    # Any declared attr the caller didn't pass defaults to None so `:if={x}`
    # truthy checks work without raising NameError.
    for attr_name in fmdict.get("attrs", {}) or {}:
        ctx.setdefault(attr_name, None)
    # The view-level context (request, DEBUG, etc.) flows down into every
    # `:include`d template so layouts and components don't have to thread it
    # explicitly. Caller-passed attrs override.
    root_ctx = root_context if root_context is not None else ctx
    scope = _build_scope(fmdict, ctx, source_path)
    out: list[str] = []
    for node in tree:
        _render_node(node, scope, source_path, root_ctx, out)
    return "".join(out)


def _build_scope(fmdict: dict, context: dict, source_path: Path | None) -> dict:
    """Construct the expression-evaluation namespace.

    Order: engine globals → template `imports:` → caller context. Caller
    context wins on conflict because attrs declared by the template arrive
    there. Python's `eval` auto-injects builtins on first use, so we don't
    seed them explicitly.
    """
    scope: dict = {}
    scope.update(all_globals())
    for stmt in fmdict.get("imports", []) or []:
        try:
            exec(stmt, scope)  # noqa: S102 — frontmatter is trusted author input
        except Exception as e:
            label = str(source_path) if source_path else "<source>"
            raise RenderError(
                f"Failed to execute import {stmt!r} in {label}: {e}"
            ) from e
    scope.update(context)
    return scope


def _render_node(
    node: Node,
    scope: dict,
    source_path: Path | None,
    root_ctx: dict,
    out: list[str],
) -> None:
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
            _render_element(node, scope, source_path, root_ctx, out)
        case _:
            raise RenderError(f"Unknown node type: {type(node).__name__}")


def _render_element(
    node: ElementNode,
    scope: dict,
    source_path: Path | None,
    root_ctx: dict,
    out: list[str],
) -> None:
    if node.if_code is not None and not _eval(node.if_code, scope):
        return

    if node.for_clause is None:
        _emit_element(node, scope, source_path, root_ctx, out)
        return

    iterable = _eval(node.for_clause.iter_code, scope)
    names = node.for_clause.targets
    for item in iterable:
        inner = dict(scope)
        _bind_targets(inner, names, item)
        _emit_element(node, inner, source_path, root_ctx, out)


def _emit_element(
    node: ElementNode,
    scope: dict,
    source_path: Path | None,
    root_ctx: dict,
    out: list[str],
) -> None:
    if node.include_path is not None or node.include_path_code is not None:
        _render_include(node, scope, source_path, root_ctx, out)
        return

    if node.tag == "template":
        # `<template>` without `:include` is a transparent fragment.
        for child in node.children:
            _render_node(child, scope, source_path, root_ctx, out)
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
        _render_node(child, scope, source_path, root_ctx, out)
    out.append("</")
    out.append(node.tag)
    out.append(">")


def _render_include(
    node: ElementNode,
    scope: dict,
    source_path: Path | None,
    root_ctx: dict,
    out: list[str],
) -> None:
    """Render `<template :include="path" attr={v}>...</template>`.

    Slots: children with `slot="name"` route into named slots; everything
    else collects in the `default` slot. `<template slot="name">` wrappers
    contribute their children (without the wrapper itself).
    """
    path_name = (
        node.include_path
        if node.include_path is not None
        else str(_eval(node.include_path_code, scope))
    )
    target_path = find_template(path_name, current_template=source_path)

    slots: dict[str, list[Node]] = {"default": []}
    for child in node.children:
        if isinstance(child, ElementNode) and child.slot_name:
            target_slot = slots.setdefault(child.slot_name, [])
            if child.tag == "template":
                target_slot.extend(child.children)
            else:
                clone = ElementNode(
                    tag=child.tag,
                    attrs=child.attrs,
                    children=child.children,
                    self_closing=child.self_closing,
                    if_code=child.if_code,
                    for_clause=child.for_clause,
                )
                target_slot.append(clone)
        else:
            slots["default"].append(child)

    rendered_slots: dict[str, SafeString] = {}
    for name, nodes in slots.items():
        chunks: list[str] = []
        for n in nodes:
            _render_node(n, scope, source_path, root_ctx, chunks)
        rendered_slots[name] = mark_safe("".join(chunks))

    attrs_passed: dict[str, object] = {}
    for attr in node.attrs:
        attrs_passed[attr.name] = _attribute_value(attr, scope)

    # Child context = view-level root context (request, DEBUG, etc.) +
    # explicit attrs from the caller + rendered slot strings. Caller wins on
    # conflict so explicit attrs override anything from root_ctx.
    child_context: dict = {}
    child_context.update(root_ctx)
    child_context.update(attrs_passed)
    child_context["children"] = rendered_slots["default"]
    for name, value in rendered_slots.items():
        if name != "default":
            child_context[name] = value
    child_context.setdefault("default", rendered_slots["default"])

    source = target_path.read_text(encoding="utf-8")
    fmdict, body = fm.split(source)
    tokens = tokenize(body)
    tree = parse(tokens)

    declared_slots = fmdict.get("slots", {}) or {}
    for slot_name in declared_slots:
        child_context.setdefault(slot_name, mark_safe(""))

    # Any declared attr the caller didn't pass defaults to None so the
    # template can use truthy checks (`:if={badge_text}`) without raising.
    for attr_name in fmdict.get("attrs", {}) or {}:
        child_context.setdefault(attr_name, None)

    sub_scope = _build_scope(fmdict, child_context, target_path)
    for n in tree:
        _render_node(n, sub_scope, target_path, root_ctx, out)


def _attribute_value(attr: Attribute, scope: dict) -> object:
    """Evaluate an attribute as a Python value (for passing as include attrs).

    Single-expression attrs return the raw value; mixed-segment attrs return
    the concatenated string after escape — but since the consumer is a child
    template's `{attr}` reference, escape would re-escape. So we concatenate
    raw values and let the child template's position-aware escape do its job.
    """
    if attr.segments is None:
        return True
    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        return _eval(attr.segments[0].code, scope)
    parts: list[str] = []
    for seg in attr.segments:
        match seg:
            case AttrText():
                parts.append(seg.text)
            case AttrExpr():
                parts.append(str(_eval(seg.code, scope)))
    return "".join(parts)


def _render_attribute(attr: Attribute, scope: dict) -> str | None:
    if attr.segments is None:
        return f" {attr.name}"

    # `name={expr}` — single expression governs boolean / list / value rendering.
    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        value = _eval(attr.segments[0].code, scope)
        if value is False or value is None:
            return None
        if value is True:
            return f" {attr.name}"
        if isinstance(value, list):
            # Flatten, drop falsy, space-join — matches the spec's `class={[...]}` rule.
            parts = [str(v) for v in _flatten(value) if v]
            if not parts:
                return None
            return f' {attr.name}="{_escape_to_str(" ".join(parts))}"'
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


def _flatten(value: object):
    """Yield items from arbitrarily nested lists/tuples; pass-through scalars."""
    if isinstance(value, list | tuple):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


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
