"""Per-attribute security policy.

Two compile-time refusals:
  - URL-bearing attributes get routed through scheme allow-list escape.
  - Event-handler attributes (`onclick=`, `onload=`, …) refuse dynamic
    data outright unless the value is a literal `mark_safe(...)` or
    `Markup(...)` call. HTML-escape doesn't protect a JS context, and
    the explicit opt-in keeps the trust decision greppable in source.
"""

from __future__ import annotations

import ast

from ..tokenizer import AttrExpr, Attribute, AttrText

# URLs in these attributes go through `escape_url` so an attacker can't slip a
# `javascript:` or `data:text/html` value into the rendered document. Phase 6
# may expand this list.
URL_ATTRS: frozenset[str] = frozenset(
    {
        "href",
        "src",
        "action",
        "formaction",
        "xlink:href",
        "data",
        "poster",
        "cite",
    }
)


def is_event_handler_attr(name: str) -> bool:
    """Whether `name` is a DOM event-handler attribute (`onclick`, `onload`, …).

    Lowercased prefix check — HTML attribute names are case-insensitive.
    """
    return name.lower().startswith("on") and len(name) > 2


def attr_has_unsafe_expr(attr: Attribute) -> bool:
    """Whether `attr` has a dynamic value that wasn't explicitly opted in.

    A single-expression value counts as opted-in only when the expression is
    a literal `mark_safe(...)` or `Markup(...)` call. Anything else, plus any
    mixed text + expr segments, is unsafe.
    """
    if attr.segments is None:
        return False
    if all(isinstance(s, AttrText) for s in attr.segments):
        return False
    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        return not _is_static_safe_call(attr.segments[0].code)
    # Mixed text + expr: even if every expr were mark_safe, the static
    # bits could still be unsafe under JS parsing rules. Refuse.
    return True


def _is_static_safe_call(code: str) -> bool:
    """Whether `code` parses as a `mark_safe(...)` or `Markup(...)` call.

    Greppable opt-in at the source level: the author wrote those names
    literally, so they're documenting the trust decision in the template.
    """
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError:
        return False
    expr = tree.body
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id in {"mark_safe", "Markup"}
    )
