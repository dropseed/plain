"""AST rewriting for template `{python expression}` fragments.

Free `Name` loads inside `{...}` get rewritten to `_ctx['name']` at
compile time, except for names bound by `:for` targets, frontmatter
`imports:`, Python builtins, and names locally bound by the expression
itself (comp / lambda / walrus).
"""

from __future__ import annotations

import ast
import builtins as _builtins_module
import keyword
from typing import Any

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


def is_promotable_name(name: str) -> bool:
    """Whether `name` can be a real Python kwarg in the emitted `render()`.

    Excludes Python keywords (which can't be parameter names) and the
    trailing-underscore aliases reserved for keyword-named attrs.
    """
    return (
        name.isidentifier()
        and not keyword.iskeyword(name)
        and name not in _KEYWORD_ALIASES
    )


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

    def _visit_comp(self, node: Any) -> Any:
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


def parse_import_bindings(stmts: list[str]) -> set[str]:
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
