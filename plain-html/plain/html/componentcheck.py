"""Structural validation for component invocations in `plain html check`.

The parser already rejects a PascalCase tag absent from `components:`.
This module closes two further structural gaps that don't need the type
checker:

- **File existence** — every `components:` entry resolves to a real
  `.html` file (`check_component_files`).
- **Slot and attribute usage** — each component-tag call site only names
  slots and attributes the component declares, provides every required
  slot, and never assigns the same slot twice (`check_component_slots`).
  plain.html has no attribute pass-through — an undeclared attr is
  silently dropped, so it's always a mistake (typo / wrong name).

Both are best-effort against a missing/broken component file: that case
is reported once by the file-existence check, and slot/attr validation
skips it rather than double-reporting or crashing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter as fm
from .loader import TemplateFileMissing, find_template
from .parser import (
    DoctypeNode,
    ElementNode,
    ForNode,
    HtmlCommentNode,
    IfNode,
    Node,
    SlotNode,
    TemplateCommentNode,
    TextNode,
)
from .positions import offset_to_line_col
from .typecheck.declarations import parse as parse_declarations


def check_component_files(
    components: dict[str, str],
    *,
    label: str,
    current_template: Path | None,
) -> list[str]:
    """Verify every `components:` entry resolves to a `.html` file.

    `current_template` is the file being checked (used to resolve
    relative `./`, `../` paths). When it's `None` (stdin mode), relative
    paths can't be resolved and are skipped rather than reported.
    """
    errors: list[str] = []
    for path in sorted(set(components.values())):
        if current_template is None and (
            path.startswith("./") or path.startswith("../")
        ):
            # No base directory to resolve a relative path against.
            continue
        try:
            find_template(path, current_template=current_template)
        except TemplateFileMissing:
            errors.append(
                f"{label}:1:1: components: entry '{path}' — template file not found"
            )
    return errors


def check_component_slots(
    nodes: list[Node],
    components: dict[str, str],
    *,
    label: str,
    source: str,
    body_start: int,
    current_template: Path | None,
) -> list[str]:
    """Validate slot and attribute usage at every component call site.

    For each `<Component>` invocation:
    - every attribute on the tag must be a declared `attrs:` entry
      (plain.html has no pass-through — an undeclared attr is dropped)
    - every `:slot="name"` child must name a slot the component declares
    - every required slot the component declares must be provided
    - no two children may target the same slot

    Each error anchors at the component tag's real line:col, computed
    from the `ElementNode`'s body offset (`source` + `body_start` map it
    back to a template position the same way `cli.py` does for parse
    errors).

    A component whose file is missing or whose frontmatter can't be
    parsed is skipped — `check_component_files` reports the missing file,
    and a broken component shouldn't crash the walk.
    """
    errors: list[str] = []
    _decl_cache: dict[str, _ComponentDecls | None] = {}

    def component_decls(path: str) -> _ComponentDecls | None:
        """Return the component's declared slots/attrs, or None if unresolved."""
        if path not in _decl_cache:
            try:
                component_path = find_template(path, current_template=current_template)
                component_source = component_path.read_text(encoding="utf-8")
                fmdict, _ = fm.split(component_source)
                decls = parse_declarations(fmdict)
            except Exception:
                # Missing / broken component — reported elsewhere.
                _decl_cache[path] = None
            else:
                _decl_cache[path] = _ComponentDecls(
                    slots={s.name for s in decls.slots},
                    required_slots={s.name for s in decls.slots if s.required},
                    attrs={a.name for a in decls.attrs},
                )
        return _decl_cache[path]

    def visit(node_list: list[Node]) -> None:
        for node in node_list:
            if isinstance(node, ElementNode):
                if node.include_path is not None:
                    _check_call_site(
                        node, errors, component_decls, label, source, body_start
                    )
                visit(node.children)
            elif isinstance(node, IfNode):
                for branch in node.branches:
                    visit(branch.children)
            elif isinstance(node, ForNode | SlotNode):
                visit(node.children)

    visit(nodes)
    return errors


@dataclass
class _ComponentDecls:
    """The slot/attr surface of a resolved component, for call-site checks."""

    slots: set[str]
    required_slots: set[str]
    attrs: set[str]


def _check_call_site(
    node: ElementNode,
    errors: list[str],
    component_decls: Callable[[str], _ComponentDecls | None],
    label: str,
    source: str,
    body_start: int,
) -> None:
    assert node.include_path is not None  # caller checks before calling
    decls = component_decls(node.include_path)
    if decls is None:
        # File missing/broken — already reported by check_component_files.
        return

    line, column = offset_to_line_col(source, body_start + node.offset)
    here = f"{label}:{line}:{column}:"

    # Attribute names — plain.html has no pass-through, so every attr
    # written on the tag must be a declared `attrs:` entry.
    for attr in node.attrs:
        if attr.name not in decls.attrs:
            errors.append(
                f"{here} unknown attr '{attr.name}' on component <{node.tag}>"
            )

    seen: set[str] = set()
    has_default_content = False
    for child in node.children:
        if isinstance(child, SlotNode):
            name = child.name
            if name not in decls.slots:
                errors.append(f"{here} unknown slot '{name}' on component <{node.tag}>")
                continue
            if name in seen:
                errors.append(
                    f"{here} component <{node.tag}> assigns slot "
                    f"'{name}' more than once"
                )
            seen.add(name)
        else:
            # Unmarked child content falls through to the default slot.
            if _is_content(child):
                has_default_content = True

    if has_default_content:
        seen.add("default")

    for name in sorted(decls.required_slots - seen):
        errors.append(
            f"{here} component <{node.tag}> is missing required slot '{name}'"
        )


def _is_content(node: Node) -> bool:
    """True for a child node that constitutes default-slot content.

    Whitespace-only text, comments, and the doctype don't count as slot
    content; an element or `{expr}` does.
    """
    if isinstance(node, TextNode):
        return bool(node.text.strip())
    if isinstance(node, HtmlCommentNode | TemplateCommentNode | DoctypeNode):
        return False
    return True
