"""AOT compile a parsed tag tree to a Python `render(...)` function.

Scope (phases 5a–5d):
  - Text (constant-folded), `{expr}`, elements, attributes.
  - `:if` / `:for` (real Python control flow).
  - `<template>` fragments + comments + doctype.
  - Frontmatter `attrs:` / `slots:` defaulting + `imports:` at module load.
  - `<template :include="literal/path">` with attr passing.
  - Slot composition: default slot + named (`slot="..."`) routing.

Not yet supported (raises `CompileError`):
  - Dynamic includes (`:include={expr}`).
  - Scoped-slot `:as`.
  - Disk cache / file-based session (5e).

Expressions are inlined as real Python sub-expressions: free `Name`
loads are AST-rewritten to `_ctx['name']` except for names bound by
`:for` targets, names imported via frontmatter, Python builtins, and
names locally bound by the expression itself (comp/lambda/walrus).

Includes are resolved at compile time. A `CompileSession` walks the
template graph depth-first and compiles each leaf before its parent,
so when the parent module is exec'd its `_inc_N` references already
point at compiled child render functions injected into module globals.
"""

from __future__ import annotations

import ast
import builtins as _builtins_module
import keyword
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .loader import find_template
from .parser import (
    DoctypeNode,
    ElementNode,
    ExprNode,
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


class CompileError(Exception):
    pass


# Resolver signature: (name, *, current_template) -> resolved Path.
# Matches `loader.find_template` so it can be used as the default.
PathResolver = Callable[..., Path]


_BUILTINS: frozenset[str] = frozenset(dir(_builtins_module)) | {
    "True",
    "False",
    "None",
}

# Trailing-underscore aliases for Python keywords (`class_`, `for_`, …). These
# stay in `_ctx` rather than being promoted to function kwargs so that the
# `normalize_keywords(_ctx)` aliasing pass at function entry can still set them
# from the original keyword-named caller key — there's no way to mutate a
# promoted local from a runtime helper.
_KEYWORD_ALIASES: frozenset[str] = frozenset(f"{k}_" for k in keyword.kwlist)


def _is_promotable_name(name: str) -> bool:
    """Whether `name` can be a real Python kwarg in the emitted `render()`.

    Excludes Python keywords (which can't be parameter names) and the
    trailing-underscore aliases reserved for keyword-named attrs.
    """
    return (
        name.isidentifier()
        and not keyword.iskeyword(name)
        and name not in _KEYWORD_ALIASES
    )


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


# --- top-level entry points -------------------------------------------------


def compile_source(source: str, *, source_label: str = "<source>") -> str:
    """Tokenize + parse + emit Python source for a standalone template.

    Use this for templates with no `:include` (the include path needs a
    `CompileSession` to resolve and recursively compile children). The
    generated module's `render` won't reference any `_inc_N` slots.
    """
    fmdict, body = fm.split(source)
    tokens = tokenize(body)
    tree = parse(tokens)
    return _emit_module(tree, fmdict, source_label, include_renders={})


def compile_tree(
    tree: list[Node],
    fmdict: dict | None = None,
    *,
    source_label: str = "<source>",
) -> str:
    """Lower-level: skip frontmatter parsing if the caller already has the tree."""
    return _emit_module(tree, fmdict or {}, source_label, include_renders={})


def compile_path(
    path: Path,
    *,
    resolver: PathResolver | None = None,
) -> Callable[..., str]:
    """Compile a template file and return its `render` function.

    Resolves and recursively compiles every `:include` along the way.
    Pass a custom `resolver` to short-circuit `loader.find_template` —
    handy for tests that want to keep template files in a tmpdir.
    """
    session = CompileSession(resolver=resolver)
    return session.compile_path(path)


# --- CompileSession ---------------------------------------------------------


class CompileSession:
    """Caches compiled templates within one build pass.

    Walks the `:include` graph depth-first: a parent is compiled only
    after every leaf it depends on has its own compiled module ready.
    Each compiled `render` is injected into the parent's module globals
    as `_inc_0`, `_inc_1`, … before the parent module is exec'd.

    A session is single-use and not thread-safe. For long-lived
    rendering, build a session once at startup and call `compile_path`
    on each entry-point template; cached results survive subsequent
    calls within the same session.
    """

    def __init__(self, *, resolver: PathResolver | None = None) -> None:
        self.resolver: PathResolver = resolver or find_template
        self._compiled: dict[Path, Callable[..., str]] = {}
        self._in_progress: set[Path] = set()

    def compile_path(self, path: Path) -> Callable[..., str]:
        path = path.resolve()
        if path in self._compiled:
            return self._compiled[path]
        if path in self._in_progress:
            raise CompileError(f"`:include` cycle detected involving {path}")
        self._in_progress.add(path)
        try:
            render_fn = self._compile_one(path)
        finally:
            self._in_progress.discard(path)
        self._compiled[path] = render_fn
        return render_fn

    def _compile_one(self, path: Path) -> Callable[..., str]:
        source = path.read_text(encoding="utf-8")
        fmdict, body = fm.split(source)
        tokens = tokenize(body)
        tree = parse(tokens)

        # Walk the tree, find every literal `:include`, recursively compile its
        # target, and assign each include site a unique `_inc_N` slot. The
        # mapping is keyed by `id(node)` so the emitter can find the right
        # slot during traversal.
        include_renders: dict[int, str] = {}
        include_funcs: dict[str, Callable[..., str]] = {}
        idx = 0
        for inc_node in _walk_includes(tree):
            if inc_node.include_path_code is not None:
                raise CompileError(
                    "dynamic `<template :include={expr}>` is not yet supported "
                    "(deferred to Phase 5e)"
                )
            assert inc_node.include_path is not None
            child_path = self.resolver(inc_node.include_path, current_template=path)
            child_render = self.compile_path(child_path)
            slot_name = f"_inc_{idx}"
            include_renders[id(inc_node)] = slot_name
            include_funcs[slot_name] = child_render
            idx += 1

        src = _emit_module(tree, fmdict, str(path), include_renders=include_renders)

        mod = types.ModuleType(f"_plain_html_compiled_{abs(hash(str(path)))}")
        mod.__file__ = str(path)
        # Inject child renderers as module globals before exec so the
        # generated bare-name references resolve.
        mod.__dict__.update(include_funcs)
        code = compile(src, str(path), "exec")
        exec(code, mod.__dict__)
        return mod.render


def _walk_includes(nodes: list[Node]) -> Iterator[ElementNode]:
    """Yield every ElementNode that has `:include` set, in tree order."""
    for node in nodes:
        if isinstance(node, ElementNode):
            if node.include_path is not None or node.include_path_code is not None:
                yield node
            yield from _walk_includes(node.children)


# --- module emission --------------------------------------------------------


def _emit_module(
    tree: list[Node],
    fmdict: dict,
    source_label: str,
    *,
    include_renders: dict[int, str],
) -> str:
    declared_attrs = list((fmdict.get("attrs") or {}).keys())
    declared_slots = list((fmdict.get("slots") or {}).keys())
    imports = list(fmdict.get("imports") or [])
    module_globals = _parse_import_bindings(imports)

    # Declared attrs/slots split into:
    #   - promoted: become real Python kwargs → faster bare-name access in
    #     expressions (no `_ctx['name']` dict subscript).
    #   - ctx-only: keyword-named (`class`) or trailing-aliased (`class_`) →
    #     stay in `_ctx` so `normalize_keywords` can still establish the alias.
    promoted_attrs = [a for a in declared_attrs if _is_promotable_name(a)]
    ctx_attrs = [a for a in declared_attrs if a not in set(promoted_attrs)]
    promoted_slots = [s for s in declared_slots if _is_promotable_name(s)]
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
        "escape_html, escape_attr, render_dyn_attr, normalize_keywords"
    )
    header.append("from plain.utils.safestring import mark_safe as _mark_safe")
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
        if _is_promotable_name(name):
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

    if all(isinstance(s, AttrText) for s in attr.segments):
        value = "".join(s.text for s in attr.segments if isinstance(s, AttrText))
        e.text(f' {attr.name}="{value}"')
        return

    if len(attr.segments) == 1 and isinstance(attr.segments[0], AttrExpr):
        e.line(
            f"{e.append_name}(render_dyn_attr({attr.name!r}, "
            f"{e.rewrite_expr(attr.segments[0].code)}))"
        )
        return

    e.text(f' {attr.name}="')
    for seg in attr.segments:
        match seg:
            case AttrText():
                e.text(seg.text)
            case AttrExpr():
                e.line(f"{e.append_name}(escape_html({e.rewrite_expr(seg.code)}))")
    e.text('"')


# --- expression AST rewriting -----------------------------------------------


def rewrite_expression(code: str, *, locals_outer: set[str]) -> str:
    """Rewrite free `Name` loads in `code` to `_ctx['name']`.

    Names left alone:
      - Anything in `locals_outer`: imports (rebound as locals from
        `_ctx` at function entry) plus active `:for` targets.
      - Python builtins.
      - Names locally bound inside the expression itself: lambda params,
        comprehension targets, walrus targets.
    """
    tree = ast.parse(code, mode="eval")
    rw = _ExprRewriter(locals_outer=locals_outer)
    new_tree = rw.visit(tree)
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree)


class _ExprRewriter(ast.NodeTransformer):
    """AST transformer for `rewrite_expression`."""

    def __init__(self, *, locals_outer: set[str]) -> None:
        # The base frame holds outer-template locals (imports + active
        # `:for` targets). Each comp/lambda pushes a new frame. Walrus
        # targets bind into the base — Python pushes them to the enclosing
        # function, which for a template expression is render() itself.
        self.scope_stack: list[set[str]] = [set(locals_outer)]

    def _is_bound(self, name: str) -> bool:
        if name in _BUILTINS:
            return True
        return any(name in frame for frame in self.scope_stack)

    def _bind_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.scope_stack[-1].add(target.id)
        elif isinstance(target, ast.Tuple | ast.List):
            for elt in target.elts:
                self._bind_target(elt)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if isinstance(node.ctx, ast.Load) and not self._is_bound(node.id):
            return ast.copy_location(
                ast.Subscript(
                    value=ast.Name(id="_ctx", ctx=ast.Load()),
                    slice=ast.Constant(value=node.id),
                    ctx=ast.Load(),
                ),
                node,
            )
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        self.scope_stack.append(set())
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.scope_stack[-1].add(arg.arg)
        if args.vararg is not None:
            self.scope_stack[-1].add(args.vararg.arg)
        if args.kwarg is not None:
            self.scope_stack[-1].add(args.kwarg.arg)
        node.body = self.visit(node.body)
        # Defaults are evaluated in the enclosing scope, not the lambda body.
        self.scope_stack.pop()
        node.args.defaults = [self.visit(d) for d in args.defaults]
        node.args.kw_defaults = [
            (self.visit(d) if d is not None else None) for d in args.kw_defaults
        ]
        return node

    def _visit_comp(self, node):  # type: ignore[no-untyped-def]
        first = node.generators[0]
        first.iter = self.visit(first.iter)
        self.scope_stack.append(set())
        self._bind_target(first.target)
        first.ifs = [self.visit(i) for i in first.ifs]
        for gen in node.generators[1:]:
            gen.iter = self.visit(gen.iter)
            self._bind_target(gen.target)
            gen.ifs = [self.visit(i) for i in gen.ifs]
        if isinstance(node, ast.DictComp):
            node.key = self.visit(node.key)
            node.value = self.visit(node.value)
        else:
            node.elt = self.visit(node.elt)
        self.scope_stack.pop()
        return node

    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_GeneratorExp = _visit_comp
    visit_DictComp = _visit_comp

    def visit_NamedExpr(self, node: ast.NamedExpr) -> ast.AST:
        # Walrus binds into the base (template) scope so the name is visible
        # to siblings within the same expression.
        self.scope_stack[0].add(node.target.id)
        node.value = self.visit(node.value)
        return node


def _parse_import_bindings(stmts: list[str]) -> set[str]:
    """Pull module-level names bound by each `imports:` statement.

    `from x import a, b as c` → {a, c}; `import x.y` → {x}.
    """
    names: set[str] = set()
    for stmt in stmts:
        try:
            tree = ast.parse(stmt, mode="exec")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
    return names
