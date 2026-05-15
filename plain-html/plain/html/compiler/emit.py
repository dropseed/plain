"""Codegen — walk a parsed tag tree and emit a Python `render()` module.

Each emitted module's `render()` returns a single str.

**Fragment coalescing.** Adjacent text and dynamic expressions accumulate
in a fragment buffer and flush as a single `list += (...)` call — collapses
N appends per run into one.

**Source mapping.** Each emitted Python line carries the template body
offset of the node that produced it. `emit_module` returns the source +
a `gen_line → tpl_offset` map; the session uses it to remap AST line
numbers so tracebacks point at the template, not the generated `.py`.

`{% if %}` / `{% for %}` blocks become real Python control flow.
Component-tag sites call the resolved child `_inc_N` render function
injected into module globals by `CompileSession`. Expression interiors
are rewritten by
`.expressions.rewrite_expression` so free names load from `_ctx`.
Attribute names are classified by `.security` so URL attrs route through
`escape_url` and event-handler attrs refuse unmarked dynamic data.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from ..parser import (
    DoctypeNode,
    ElementNode,
    ExprNode,
    ForNode,
    HtmlCommentNode,
    IfNode,
    Node,
    RawNode,
    SlotNode,
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


# A fragment is either a literal text chunk or a Python expression whose
# runtime value is a string. Each frag carries the template body offset of
# the node that produced it, so the flushed `_append(...)` line gets stamped
# with a useful offset for source mapping.
@dataclass
class _Frag:
    kind: str  # "text" or "expr"
    content: str  # raw text for "text", Python expr source for "expr"
    offset: int  # body offset in the template source


@dataclass
class _Emit:
    """Codegen state for a single `render()` function body.

    Fragment buffer (`pending`) accumulates adjacent text and expression
    fragments. They flush as ONE `_append(...)` call when control flow,
    a slot boundary, or a non-append statement forces the boundary —
    constant folding plus dynamic coalescing.

    `local_stack` tracks names that are real Python locals at each
    nesting level. Imports are at the base; each `:for` pushes a frame.

    `target_list` is the Python identifier of the buffer (a `list[str]`)
    we're currently appending to. It defaults to `_out` (the function's
    output buffer) and switches to per-slot accumulator names while
    rendering a component's slot children — that's how the same emission
    machinery can produce sub-buffers without copying.

    `include_renders` maps each component-tag node (by id) to the Python
    name (`_inc_0`, `_inc_1`, …) that the CompileSession will inject
    into module globals before exec.

    `line_offsets` records the template body offset for every emitted
    Python line (parallel to `lines`). The session uses this to map AST
    line numbers back into template positions for tracebacks.
    """

    lines: list[str] = field(default_factory=list)
    line_offsets: list[int] = field(default_factory=list)
    indent: int = 1
    pending: list[_Frag] = field(default_factory=list)
    local_stack: list[set[str]] = field(default_factory=lambda: [set()])
    target_list: str = "_out"
    include_renders: dict[int, str] = field(default_factory=dict)
    current_offset: int = 0
    _acc_counter: int = 0
    # When False (text mode — Markdown bodies), text-position expressions
    # emit `to_text(...)` instead of `escape_html(...)`: the output isn't
    # HTML, so escaping would corrupt it.
    escape: bool = True

    def text(self, s: str) -> None:
        if s:
            self.pending.append(_Frag("text", s, self.current_offset))

    def expr_frag(self, code: str) -> None:
        """Append a dynamic expression to the fragment buffer.

        `code` must be a Python expression whose runtime value is a
        `str` (raw, already escaped for its position). The output is
        concatenated directly into the buffer's flushed `_append` call.
        """
        self.pending.append(_Frag("expr", code, self.current_offset))

    def line(self, body: str, *, offset: int | None = None) -> None:
        self._flush()
        self.lines.append("    " * self.indent + body)
        self.line_offsets.append(self.current_offset if offset is None else offset)

    def block_start(self, header: str, *, offset: int | None = None) -> None:
        self._flush()
        self.lines.append("    " * self.indent + header)
        self.line_offsets.append(self.current_offset if offset is None else offset)
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

    def fresh_acc(self) -> tuple[str, str]:
        """Allocate fresh accumulator var names for a slot sub-buffer.

        Returns (list_var, value_var) — the buffer name and the materialized
        slot-value name. No cached `.append` shortcut here: emit uses
        `{list}.append(x)` for single fragments and `{list} += (...)` for
        multi, so the list itself is all the codegen needs.
        """
        idx = self._acc_counter
        self._acc_counter += 1
        return f"_slot_acc_{idx}", f"_slot_val_{idx}"

    def _flush(self) -> None:
        if not self.pending:
            return
        frags = self.pending
        self.pending = []

        # Coalesce runs of text into single text frags so a 3-fragment run
        # that's actually all literal collapses cleanly to one append.
        coalesced: list[_Frag] = []
        for f in frags:
            if f.kind == "text" and coalesced and coalesced[-1].kind == "text":
                last = coalesced[-1]
                coalesced[-1] = _Frag("text", last.content + f.content, last.offset)
            else:
                coalesced.append(f)

        # Stamp the emitted line with the offset of the first expression
        # frag (or the first text frag if there are no expressions). An
        # error during expression eval points at the line of the first
        # expression in the run — close enough for the traceback line.
        line_offset = next((f.offset for f in coalesced if f.kind == "expr"), 0)
        if not line_offset:
            line_offset = coalesced[0].offset

        if len(coalesced) == 1:
            # Single-fragment runs: one `list.append(x)` call. Cheap, and
            # avoids the tuple-build that `+=` would do for free.
            f = coalesced[0]
            payload = repr(f.content) if f.kind == "text" else f.content
            body = f"{self.target_list}.append({payload})"
        else:
            # Multi-fragment runs: build one tuple, push it in one go via
            # `list += (...)` (i.e. `list.__iadd__`, the in-place extend).
            # Trailing comma keeps a 2-frag tuple unambiguous.
            parts: list[str] = []
            for f in coalesced:
                parts.append(repr(f.content) if f.kind == "text" else f.content)
            body = f"{self.target_list} += ({', '.join(parts)},)"

        self.lines.append("    " * self.indent + body)
        self.line_offsets.append(line_offset)


@dataclass
class EmittedModule:
    """Output of `emit_module` — Python source plus the line→offset map.

    `source` is the full generated module text. `line_offsets[k]` is
    the template body offset that produced generated line `k + 1`
    (1-based gen line, 0-indexed list). Entries are `0` for boilerplate
    lines that don't correspond to a template node — the session's
    AST-remap step treats those as "no mapping" and skips them.
    """

    source: str
    line_offsets: list[int]


def _attr_default_sources(attrs_raw: dict) -> dict[str, str]:
    """Map declared attrs to their default-value Python source.

    Attrs declared without a default are absent from the result. The
    inline string form (`type = default`) is split via Python's
    annotated-assignment grammar; the expanded mapping form reads the
    `default:` key. This mirrors the default extraction in
    `typecheck/declarations.py` so the runtime `render()` signature
    carries the same defaults the type checker validates against.
    """
    defaults: dict[str, str] = {}
    for name, value in attrs_raw.items():
        if isinstance(value, str):
            node = ast.parse(f"_d: {value.strip()}", mode="exec").body[0]
            if isinstance(node, ast.AnnAssign) and node.value is not None:
                defaults[name] = ast.unparse(node.value)
        elif isinstance(value, dict) and "default" in value:
            defaults[name] = repr(value["default"])
    return defaults


def emit_module(
    tree: list[Node],
    fmdict: dict,
    source_label: str,
    *,
    include_renders: dict[int, str],
    escape: bool = True,
) -> EmittedModule:
    """Emit a complete Python module + per-line template offset map.

    `escape=False` selects text mode (Markdown page bodies): text-position
    expressions emit `to_text(...)` rather than `escape_html(...)`.
    """
    attrs_raw = fmdict.get("attrs") or {}
    declared_attrs = list(attrs_raw.keys())
    attr_defaults = _attr_default_sources(attrs_raw)
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

    e = _Emit(include_renders=include_renders, escape=escape)
    # Imports + promoted attrs/slots are all real Python locals — tell the
    # rewriter to leave bare references alone for any of them.
    e.local_stack[0] |= module_globals
    e.local_stack[0] |= set(promoted_attrs)
    e.local_stack[0] |= set(promoted_slots)
    _emit_nodes(tree, e)
    e._flush()

    header: list[str] = []
    header.append('"""Auto-generated by plain.html.compiler. DO NOT EDIT."""')
    header.append("from __future__ import annotations")
    header.append("")
    header.append(
        "from plain.html._runtime import "
        "escape_html, escape_url, to_text, "
        "render_dyn_attr, render_dyn_url_attr, normalize_keywords"
    )
    header.append("from plain.utils.safestring import mark_safe")
    # `Markup` is the spec-named alias users reach for; `_mark_safe` is the
    # codegen's private alias — `mark_safe` and `Markup` get re-bound from
    # `_ctx` per render call, so internal call sites use `_mark_safe` to
    # avoid the user-shadowing path.
    header.append("Markup = _mark_safe = mark_safe")
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
        sig_params.append(f"{name}={attr_defaults.get(name, 'None')}")
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
        # the param falls back to its signature default (`None` when the
        # attr declared no default). Only the `None` case pulls the
        # ambient value from `_ctx` — a declared default is a deliberate
        # value and wins over ambient leakage; an explicit non-None pass
        # wins because it skips this rebind too.
        for name in promoted_all:
            body_lines.append(f"        if {name} is None:")
            body_lines.append(f"            {name} = _ctx.get({name!r})")
    else:
        body_lines.append("    if _root_ctx is None:")
        body_lines.append("        _root_ctx = _ctx")
        body_lines.append("    else:")
        body_lines.append("        _ctx = {**_root_ctx, **_ctx}")
    # Keyword-named declared attrs/slots stay in _ctx — seed their
    # declared default (or `None`) via `setdefault`. `normalize_keywords`
    # will then alias `class` → `class_`, `for` → `for_`, etc. so
    # templates can write `{class_}` to access them.
    for name in ctx_attrs:
        body_lines.append(
            f"    _ctx.setdefault({name!r}, {attr_defaults.get(name, 'None')})"
        )
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
    # Track where the emitted lines start in body_lines so we can stitch
    # their per-line offsets back into the final source-wide offset list.
    emit_start_idx = len(body_lines)
    body_lines.extend(e.lines)
    body_lines.append("    return ''.join(_out)")

    source = "\n".join(header + body_lines) + "\n"

    # Build a per-generated-line offset list. Header and setup lines get `0`
    # (no template mapping); body lines that came from emission get their
    # recorded template offset. The final length is exactly the number of
    # lines in `source`.
    line_offsets: list[int] = [0] * len(header)
    line_offsets.extend([0] * emit_start_idx)
    line_offsets.extend(e.line_offsets)
    line_offsets.append(0)  # trailing `return` statement
    # The source ends with a trailing newline; `splitlines()` won't count it,
    # so `line_offsets` already matches the line count.
    assert len(line_offsets) == source.count("\n"), (
        f"line_offsets ({len(line_offsets)}) does not match generated line "
        f"count ({source.count(chr(10))})"
    )
    return EmittedModule(source=source, line_offsets=line_offsets)


# --- per-node emission ------------------------------------------------------


def _emit_nodes(nodes: list[Node], e: _Emit) -> None:
    """Emit a sequence of sibling nodes."""
    for node in nodes:
        _emit_node(node, e)


def _emit_block_children(children: list[Node], e: _Emit) -> None:
    """Emit a block branch body, inserting `pass` if it produces nothing.

    An `{% if %}` / `{% for %}` branch can be empty (whitespace only);
    the generated Python suite still needs a statement.
    """
    before = (len(e.lines), len(e.pending))
    _emit_nodes(children, e)
    if (len(e.lines), len(e.pending)) == before:
        e.line("pass")


def _emit_node(node: Node, e: _Emit) -> None:
    # Stamp every text/expr fragment emitted from this node with the node's
    # body offset so flushed `_append(...)` lines map back to the template.
    saved_offset = e.current_offset
    e.current_offset = node.offset or saved_offset
    try:
        match node:
            case TextNode():
                e.text(node.text)
            case RawNode():
                e.text(node.text)
            case ExprNode():
                helper = "escape_html" if e.escape else "to_text"
                e.expr_frag(f"{helper}({e.rewrite_expr(node.code)})")
            case HtmlCommentNode():
                e.text(f"<!--{node.text}-->")
            case TemplateCommentNode():
                pass
            case DoctypeNode():
                e.text(node.text)
            case IfNode():
                _emit_if(node, e)
            case ForNode():
                _emit_for(node, e)
            case SlotNode():
                raise CompileError(
                    "`{% slot %}` can only appear as a direct child of a component tag"
                )
            case ElementNode():
                _emit_element(node, e)
            case _:
                raise CompileError(f"Unknown node type: {type(node).__name__}")
    finally:
        e.current_offset = saved_offset


def _emit_if(node: IfNode, e: _Emit) -> None:
    """Emit an `{% if %}` chain as Python `if / elif* / else?`."""
    for idx, branch in enumerate(node.branches):
        saved_offset = e.current_offset
        e.current_offset = branch.offset or node.offset or saved_offset
        if idx == 0:
            assert branch.condition is not None
            e.block_start(f"if {e.rewrite_expr(branch.condition)}:")
        elif branch.condition is not None:
            e.block_start(f"elif {e.rewrite_expr(branch.condition)}:")
        else:
            e.block_start("else:")
        e.current_offset = saved_offset
        _emit_block_children(branch.children, e)
        e.block_end()


def _emit_for(node: ForNode, e: _Emit) -> None:
    """Emit a `{% for %}` loop as a Python `for` block."""
    clause = node.clause
    iter_expr = e.rewrite_expr(clause.iter_code)
    targets = clause.raw_target or ", ".join(clause.targets)
    e.block_start(f"for {targets} in {iter_expr}:")
    # Loop targets become real Python locals inside the for body.
    e.push_locals(set(clause.targets))
    if clause.filter_code is not None:
        e.block_start(f"if {e.rewrite_expr(clause.filter_code)}:")
        _emit_block_children(node.children, e)
        e.block_end()
    else:
        _emit_block_children(node.children, e)
    e.pop_locals()
    e.block_end()


def _emit_element(node: ElementNode, e: _Emit) -> None:
    if node.include_path is not None:
        _emit_static_include(node, e)
        return
    e.text(f"<{node.tag}")
    for attr in node.attrs:
        _emit_attribute(attr, e)
    e.text(">")
    if not (node.self_closing or node.tag in VOID_ELEMENTS):
        _emit_nodes(node.children, e)
        e.text(f"</{node.tag}>")


def _emit_static_include(node: ElementNode, e: _Emit) -> None:
    """Emit code for a component-tag site (`<Card ...>...</Card>`).

    Slot routing:
      - A `{% slot "name" %}` child routes its children into the named
        slot.
      - All other children collect in the `default` slot.

    Each slot's content is rendered in the PARENT's scope into a fresh
    accumulator (`_slot_acc_N`). The rendered strings are passed to the
    child as kwargs, alongside the component's explicit attrs and the
    propagated `_root_ctx`.
    """
    # Component sites have a pre-assigned `_inc_N` slot in module globals
    # populated by the CompileSession.
    slot_name_var = e.include_renders.get(id(node))
    if slot_name_var is None:
        raise CompileError(
            "internal: component site missing from compile session — "
            "this shouldn't happen unless CompileSession.compile_string() "
            "was used on a template that needs compile_path()"
        )

    default_children: list[Node] = []
    named_slots: dict[str, list[Node]] = {}
    for child in node.children:
        if isinstance(child, SlotNode):
            named_slots.setdefault(child.name, []).extend(child.children)
        else:
            default_children.append(child)

    default_var = _render_slot_to_var(default_children, e)
    named_vars = {
        name: _render_slot_to_var(children, e) for name, children in named_slots.items()
    }

    # Direct kwargs where the name is a valid Python identifier; fall back
    # to dict expansion only for keyword-named attrs like `class` or `for`.
    # `_root_ctx` travels as a single parameter and merges into the child's
    # `_ctx` once, at the child's function entry.
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

    # Component call result is a `str` — feed into the fragment buffer so the
    # call coalesces with surrounding text rather than emitting a standalone
    # `_append(...)`. In a component-in-loop body that matters: the loop
    # iteration drops from "3 calls + the component" to "1 call wrapping
    # everything in the run".
    e.expr_frag(f"{slot_name_var}({', '.join(parts)})")


def _render_slot_to_var(children: list[Node], e: _Emit) -> str:
    """Emit code that renders `children` into a fresh accumulator var.

    Returns the Python identifier holding the slot's rendered Markup
    string. If `children` is empty, skips the accumulator and returns a
    literal `_mark_safe('')` expression so the include call's kwargs
    dict stays simple.
    """
    if not children:
        return "_mark_safe('')"

    acc_var, value_var = e.fresh_acc()
    e.line(f"{acc_var} = []")

    saved = e.target_list
    e.target_list = acc_var
    _emit_nodes(children, e)
    e._flush()
    e.target_list = saved

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
        # Pick a quote that doesn't appear in the value, matching the
        # formatter. If both quotes appear, fall back to `"..."` with
        # `"` entity-escaped — anything else would produce invalid HTML
        # (the next `"` would terminate the attribute early).
        if '"' not in value:
            e.text(f' {attr.name}="{value}"')
        elif "'" not in value:
            e.text(f" {attr.name}='{value}'")
        else:
            e.text(f' {attr.name}="{value.replace(chr(34), "&quot;")}"')
        return

    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        helper = "render_dyn_url_attr" if is_url_attr else "render_dyn_attr"
        e.expr_frag(f"{helper}({attr.name!r}, {e.rewrite_expr(attr.segments[0].code)})")
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
        e.expr_frag(f"escape_url({' + '.join(parts)})")
        e.text('"')
        return

    e.text(f' {attr.name}="')
    for seg in attr.segments:
        match seg:
            case AttrText():
                e.text(seg.text)
            case AttrExpr():
                e.expr_frag(f"escape_html({e.rewrite_expr(seg.code)})")
    e.text('"')
