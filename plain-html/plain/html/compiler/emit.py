"""Codegen — walk a parsed tag tree and emit a Python `render()` module.

Each emitted module's `render()` returns a single str. Adjacent literal
text is constant-folded into one `_append(...)` call per run. `:if` /
`:for` become real Python control flow. `:include` sites call the
resolved child `_inc_N` render function injected into module globals by
`CompileSession`.

Expression interiors are rewritten by `.expressions.rewrite_expression`
so free names load from `_ctx`. Attribute names are classified by
`.security` so URL attrs route through `escape_url` and event-handler
attrs refuse unmarked dynamic data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..parser import (
    DoctypeNode,
    ElementNode,
    ExprNode,
    HtmlCommentNode,
    Node,
    TemplateCommentNode,
    TextNode,
)
from ..tokenizer import (
    VOID_ELEMENTS,
    AttrExpr,
    Attribute,
    AttrText,
)
from . import CompileError
from .expressions import (
    is_promotable_name,
    parse_import_bindings,
    rewrite_expression,
)
from .security import URL_ATTRS, attr_has_unsafe_expr, is_event_handler_attr


@dataclass
class _Emit:
    """Codegen state for a single `render()` function body.

    Adjacent literal text accumulates in `pending` and flushes as one
    append call when something dynamic arrives or a block boundary
    forces it — the constant-fold pass.

    `local_stack` tracks names that are real Python locals at each
    nesting level. Imports are at the base; each `:for` pushes a frame.

    `append_name` is the Python identifier we're currently appending
    to. It defaults to `_append` (the main output buffer) and switches
    to per-slot accumulator names while rendering an include's slot
    children — that's how the same emission machinery can produce
    sub-buffers without copying.

    `include_renders` maps each `:include` node (by id) to the Python
    name (`_inc_0`, `_inc_1`, …) that the CompileSession will inject
    into module globals before exec.
    """

    lines: list[str] = field(default_factory=list)
    indent: int = 1
    pending: list[str] = field(default_factory=list)
    local_stack: list[set[str]] = field(default_factory=lambda: [set()])
    append_name: str = "_append"
    include_renders: dict[int, str] = field(default_factory=dict)
    _acc_counter: int = 0

    def text(self, s: str) -> None:
        if s:
            self.pending.append(s)

    def line(self, body: str) -> None:
        self._flush()
        self.lines.append("    " * self.indent + body)

    def block_start(self, header: str) -> None:
        self._flush()
        self.lines.append("    " * self.indent + header)
        self.indent += 1

    def block_end(self) -> None:
        self._flush()
        self.indent -= 1

    def push_locals(self, names: set[str] | None = None) -> None:
        self.local_stack.append(set(names or ()))

    def pop_locals(self) -> None:
        self.local_stack.pop()

    def known_locals(self) -> set[str]:
        out: set[str] = set()
        for frame in self.local_stack:
            out |= frame
        return out

    def rewrite_expr(self, code: str) -> str:
        return rewrite_expression(code, locals_outer=self.known_locals())

    def fresh_acc(self) -> tuple[str, str, str]:
        """Allocate fresh accumulator var names for a slot sub-buffer.

        Returns (list_var, append_var, value_var).
        """
        idx = self._acc_counter
        self._acc_counter += 1
        return f"_slot_acc_{idx}", f"_slot_app_{idx}", f"_slot_val_{idx}"

    def _flush(self) -> None:
        if not self.pending:
            return
        chunk = "".join(self.pending)
        self.pending.clear()
        self.lines.append("    " * self.indent + f"{self.append_name}({chunk!r})")


def emit_module(
    tree: list[Node],
    fmdict: dict,
    source_label: str,
    *,
    include_renders: dict[int, str],
) -> str:
    """Emit a complete Python module source string for one template."""
    declared_attrs = list((fmdict.get("attrs") or {}).keys())
    declared_slots = list((fmdict.get("slots") or {}).keys())
    imports = list(fmdict.get("imports") or [])
    # Always-available names in compiled modules: `mark_safe` / `Markup` are
    # the spec-named escape-opt-in primitives. Authors should be able to
    # write `<a onclick={mark_safe(handler)}>` without an `imports:` block.
    module_globals = parse_import_bindings(imports) | {"mark_safe", "Markup"}

    # Declared attrs/slots split into:
    #   - promoted: become real Python kwargs → faster bare-name access in
    #     expressions (no `_ctx['name']` dict subscript).
    #   - ctx-only: keyword-named (`class`) or trailing-aliased (`class_`) →
    #     stay in `_ctx` so `normalize_keywords` can still establish the alias.
    promoted_attrs = [a for a in declared_attrs if is_promotable_name(a)]
    ctx_attrs = [a for a in declared_attrs if a not in set(promoted_attrs)]
    promoted_slots = [s for s in declared_slots if is_promotable_name(s)]
    ctx_slots = [s for s in declared_slots if s not in set(promoted_slots)]

    e = _Emit(include_renders=include_renders)
    # Imports + promoted attrs/slots are all real Python locals — tell the
    # rewriter to leave bare references alone for any of them.
    e.local_stack[0] |= module_globals
    e.local_stack[0] |= set(promoted_attrs)
    e.local_stack[0] |= set(promoted_slots)
    for node in tree:
        _emit_node(node, e)
    e._flush()

    header: list[str] = []
    header.append('"""Auto-generated by plain.html.compiler. DO NOT EDIT."""')
    header.append("from __future__ import annotations")
    header.append("")
    header.append(
        "from plain.html._runtime import "
        "escape_html, escape_attr, escape_url, "
        "render_dyn_attr, render_dyn_url_attr, normalize_keywords, "
        "resolve_dynamic_include as _resolve_dynamic_include"
    )
    header.append(
        "from plain.utils.safestring import "
        "mark_safe, mark_safe as Markup, mark_safe as _mark_safe"
    )
    header.append("")
    header.append(f"__template_source__ = {source_label!r}")
    header.append("")

    if imports:
        header.append("# Frontmatter imports:")
        for stmt in imports:
            header.append(stmt)
        header.append("")

    # `_root_ctx` threads the view's original context through every `:include`
    # boundary so layouts and components see `request`, `DEBUG`, etc. without
    # the caller having to repass them. `_root_ctx=None` at the top-level call
    # means "this is the entry render; _ctx is the root."
    sig_params = ["*", "_root_ctx=None"]
    for name in promoted_attrs:
        sig_params.append(f"{name}=None")
    for name in promoted_slots:
        sig_params.append(f"{name}=_mark_safe('')")
    sig_params.append("**_ctx")
    header.append(f"def render({', '.join(sig_params)}) -> str:")

    body_lines: list[str] = []
    # Entry-point (no `_root_ctx` arrived from a parent): build it from the
    # caller's kwargs, including any promoted-to-real-parameter names so
    # later `:include`s see the full view context. Otherwise (`_root_ctx`
    # passed by a parent include), merge it into `_ctx` so the rewriter's
    # `_ctx['name']` lookups can find names that arrived via `_root_ctx`
    # rather than via explicit kwargs. Doing the merge here instead of at
    # every include call site avoids the O(call_sites × dict_size) cost on
    # `:include`-in-loop templates.
    promoted_all = promoted_attrs + promoted_slots
    if promoted_all:
        merge = ", ".join(f"{n!r}: {n}" for n in promoted_all)
        body_lines.append("    if _root_ctx is None:")
        body_lines.append(f"        _root_ctx = {{{merge}, **_ctx}}")
        body_lines.append("    else:")
        body_lines.append("        _ctx = {**_root_ctx, **_ctx}")
        # When a parent include omits a promoted attr the child declared,
        # the param defaults to None. Pull the ambient value from _ctx
        # (which now has _root_ctx merged in). Explicit non-None passes win
        # because they skip this rebind.
        for name in promoted_all:
            body_lines.append(f"        if {name} is None:")
            body_lines.append(f"            {name} = _ctx.get({name!r})")
    else:
        body_lines.append("    if _root_ctx is None:")
        body_lines.append("        _root_ctx = _ctx")
        body_lines.append("    else:")
        body_lines.append("        _ctx = {**_root_ctx, **_ctx}")
    # Keyword-named declared attrs/slots stay in _ctx — apply their defaults
    # the old way. `normalize_keywords` will then alias `class` → `class_`,
    # `for` → `for_`, etc. so templates can write `{class_}` to access them.
    for name in ctx_attrs:
        body_lines.append(f"    _ctx.setdefault({name!r}, None)")
    for name in ctx_slots:
        body_lines.append(f"    _ctx.setdefault({name!r}, _mark_safe(''))")
    body_lines.append("    normalize_keywords(_ctx)")
    # Rebind imports as locals so caller-passed overrides shadow the
    # module-level import. Read the fallback through `globals()` so Python
    # doesn't flag the bare name as a self-referential local.
    if module_globals:
        body_lines.append("    _G = globals()")
        for name in sorted(module_globals):
            body_lines.append(f"    {name} = _ctx.get({name!r}, _G[{name!r}])")
    body_lines.append("    _out: list[str] = []")
    body_lines.append("    _append = _out.append")
    body_lines.extend(e.lines)
    body_lines.append("    return ''.join(_out)")

    return "\n".join(header + body_lines) + "\n"


# --- per-node emission ------------------------------------------------------


def _emit_node(node: Node, e: _Emit) -> None:
    match node:
        case TextNode():
            e.text(node.text)
        case ExprNode():
            e.line(f"{e.append_name}(escape_html({e.rewrite_expr(node.code)}))")
        case HtmlCommentNode():
            e.text(f"<!--{node.text}-->")
        case TemplateCommentNode():
            pass
        case DoctypeNode():
            e.text(node.text)
        case ElementNode():
            _emit_element(node, e)
        case _:
            raise CompileError(f"Unknown node type: {type(node).__name__}")


def _emit_element(node: ElementNode, e: _Emit) -> None:
    # `:if` / `:for` wrap whatever the element emits — including an include
    # call. Evaluate them in the outer scope before the element body.
    if node.if_code is not None:
        e.block_start(f"if {e.rewrite_expr(node.if_code)}:")

    if node.for_clause is not None:
        iter_expr = e.rewrite_expr(node.for_clause.iter_code)
        targets = node.for_clause.raw_target or ", ".join(node.for_clause.targets)
        e.block_start(f"for {targets} in {iter_expr}:")
        # Loop targets become real Python locals inside the for body.
        e.push_locals(set(node.for_clause.targets))

    if node.include_path is not None or node.include_path_code is not None:
        _emit_static_include(node, e)
    elif node.tag == "template":
        # Transparent fragment — emit children inline, no wrapper.
        # `slot_name` here is harmless metadata; it only matters when this
        # template is a direct child of a parent `:include` (handled by the
        # parent's slot routing, not by this branch).
        for child in node.children:
            _emit_node(child, e)
    else:
        e.text(f"<{node.tag}")
        for attr in node.attrs:
            _emit_attribute(attr, e)
        e.text(">")
        if not (node.self_closing or node.tag in VOID_ELEMENTS):
            for child in node.children:
                _emit_node(child, e)
            e.text(f"</{node.tag}>")

    if node.for_clause is not None:
        e.pop_locals()
        e.block_end()
    if node.if_code is not None:
        e.block_end()


def _emit_static_include(node: ElementNode, e: _Emit) -> None:
    """Emit code for a `<template :include="..." ...>...</template>` site.

    Slot routing matches the interpreter's `_render_include`:
      - Children with `slot="name"` route into the named slot.
        `<template slot="x">` contributes only its inner children
        (the `<template>` wrapper is dropped). Other elements with
        `slot="..."` contribute the element itself (the parser already
        stripped the `slot` attribute from `attrs`).
      - All other children collect in the `default` slot.

    Each slot's content is rendered in the PARENT's scope into a fresh
    accumulator (`_slot_acc_N`). The rendered strings are passed to the
    child as kwargs, alongside the include's explicit attrs and the
    propagated `_root_ctx`.
    """
    # Static include sites have a pre-assigned `_inc_N` slot in module globals
    # populated by the CompileSession; dynamic sites resolve at render time.
    is_dynamic = node.include_path_code is not None
    if is_dynamic:
        dyn_path_expr = e.rewrite_expr(node.include_path_code)  # type: ignore[arg-type]
        # Each dynamic site needs its own local to hold the resolved render
        # fn — `id(node)` makes the name unique across nested includes.
        slot_name_var = f"_inc_dyn_{abs(id(node))}"
    else:
        slot_name_var = e.include_renders.get(id(node))
        if slot_name_var is None:
            raise CompileError(
                "internal: `:include` site missing from compile session — "
                "this shouldn't happen unless compile_source() was used on a "
                "template that needs CompileSession"
            )

    default_children: list[Node] = []
    named_slots: dict[str, list[Node]] = {}
    for child in node.children:
        if isinstance(child, ElementNode) and child.slot_name is not None:
            target = named_slots.setdefault(child.slot_name, [])
            if child.tag == "template":
                target.extend(child.children)
            else:
                target.append(child)
        else:
            default_children.append(child)

    default_var = _render_slot_to_var(default_children, e)
    named_vars = {
        name: _render_slot_to_var(children, e) for name, children in named_slots.items()
    }

    # Direct kwargs where the name is a valid Python identifier; fall back
    # to dict expansion only for keyword-named attrs like `class` or `for`.
    # The previous `**{**_root_ctx, ...}` form built a fresh merged dict on
    # every call — costly inside `:include`-in-loop. `_root_ctx` now travels
    # as a single parameter and merges into the child's `_ctx` once, at the
    # child's function entry.
    direct: list[str] = []
    dict_items: list[str] = []

    def _emit_kw(name: str, value_expr: str) -> None:
        if is_promotable_name(name):
            direct.append(f"{name}={value_expr}")
        else:
            dict_items.append(f"{name!r}: {value_expr}")

    for attr in node.attrs:
        _emit_kw(attr.name, _attr_value_expr(attr, e))
    direct.append(f"children={default_var}")
    direct.append(f"default={default_var}")
    for name, var in named_vars.items():
        _emit_kw(name, var)

    parts = ["_root_ctx=_root_ctx", *direct]
    if dict_items:
        parts.append("**{" + ", ".join(dict_items) + "}")

    if is_dynamic:
        # Resolve the target template once per render of this site, then call.
        e.line(
            f"{slot_name_var} = _resolve_dynamic_include("
            f"{dyn_path_expr}, current_template=__template_source__)"
        )
    e.line(f"{e.append_name}({slot_name_var}({', '.join(parts)}))")


def _render_slot_to_var(children: list[Node], e: _Emit) -> str:
    """Emit code that renders `children` into a fresh accumulator var.

    Returns the Python identifier holding the slot's rendered Markup
    string. If `children` is empty, skips the accumulator and returns a
    literal `_mark_safe('')` expression so the include call's kwargs
    dict stays simple.
    """
    if not children:
        return "_mark_safe('')"

    acc_var, app_var, value_var = e.fresh_acc()
    e.line(f"{acc_var} = []")
    e.line(f"{app_var} = {acc_var}.append")

    saved = e.append_name
    e.append_name = app_var
    for child in children:
        _emit_node(child, e)
    e._flush()
    e.append_name = saved

    e.line(f"{value_var} = _mark_safe(''.join({acc_var}))")
    return value_var


def _attr_value_expr(attr: Attribute, e: _Emit) -> str:
    """Return a Python expression string for an attribute's runtime value.

    Matches `engine._attribute_value`: boolean (no `=`) → `True`; single
    `{expr}` → the raw expression; mixed segments → string concat with
    `str(...)` coercion on each expression.
    """
    if attr.segments is None:
        return "True"
    if all(isinstance(s, AttrText) for s in attr.segments):
        text = "".join(s.text for s in attr.segments if isinstance(s, AttrText))
        return repr(text)
    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        return e.rewrite_expr(attr.segments[0].code)
    parts: list[str] = []
    for seg in attr.segments:
        if isinstance(seg, AttrText):
            parts.append(repr(seg.text))
        else:
            parts.append(f"str({e.rewrite_expr(seg.code)})")
    return "(" + " + ".join(parts) + ")"


def _emit_attribute(attr: Attribute, e: _Emit) -> None:
    if attr.segments is None:
        e.text(f" {attr.name}")
        return

    # Event-handler attrs (`onclick=`, `onload=`, …) execute the value as JS
    # in the browser. HTML-escape does NOT protect that context — the browser
    # decodes entities before parsing the value as code. Refuse dynamic data
    # here at compile time; authors who genuinely need it must wrap the value
    # in `mark_safe(...)` or `Markup(...)` to make the opt-in explicit and
    # greppable in their template.
    if is_event_handler_attr(attr.name) and attr_has_unsafe_expr(attr):
        raise CompileError(
            f"`<...{attr.name}={{expr}}>`: event-handler attributes can't take "
            f"dynamic data — HTML escape doesn't protect a JS context. If the "
            f"value is genuinely safe, wrap it in `mark_safe(...)` to opt in."
        )

    is_url_attr = attr.name in URL_ATTRS

    if all(isinstance(s, AttrText) for s in attr.segments):
        value = "".join(s.text for s in attr.segments if isinstance(s, AttrText))
        e.text(f' {attr.name}="{value}"')
        return

    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        helper = "render_dyn_url_attr" if is_url_attr else "render_dyn_attr"
        e.line(
            f"{e.append_name}({helper}({attr.name!r}, "
            f"{e.rewrite_expr(attr.segments[0].code)}))"
        )
        return

    # Mixed text + expr segments. For URL attrs we have to compose the full
    # value before scheme validation, so we route the whole concatenation
    # through `escape_url` at the end.
    if is_url_attr:
        parts: list[str] = []
        for seg in attr.segments:
            match seg:
                case AttrText():
                    parts.append(repr(seg.text))
                case AttrExpr():
                    parts.append(f"str({e.rewrite_expr(seg.code)})")
        e.text(f' {attr.name}="')
        e.line(f"{e.append_name}(escape_url({' + '.join(parts)}))")
        e.text('"')
        return

    e.text(f' {attr.name}="')
    for seg in attr.segments:
        match seg:
            case AttrText():
                e.text(seg.text)
            case AttrExpr():
                e.line(f"{e.append_name}(escape_html({e.rewrite_expr(seg.code)}))")
    e.text('"')
