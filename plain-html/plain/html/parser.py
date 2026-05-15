"""Tag tree builder.

Consumes the tokenizer's flat stream and produces a tree of nodes.
Control flow lives in `{% %}` block tags, which become `IfNode`,
`ForNode`, and `SlotNode` tree nodes.

The builder is **HTML-aware**: a block branch must contain balanced
HTML. An element opened inside a branch must be closed inside the same
branch, and a `{% %}` block opened inside an element must be closed
inside it. A straddle (`{% if %}<div>{% endif %}…`) is a `ParseError`.

A PascalCase tag is a component invocation: the parser looks it up in
the `components:` map and sets `include_path`, reusing the component
compile backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tokenizer import (
    VOID_ELEMENTS,
    Attribute,
    BlockToken,
    DoctypeToken,
    EndTagToken,
    ExprToken,
    HtmlCommentToken,
    RawToken,
    StartTagToken,
    TemplateCommentToken,
    TextToken,
    Token,
)


class ParseError(Exception):
    pass


@dataclass
class ForClause:
    """A pre-parsed `target in iterable` clause from a `{% for %}` tag.

    `filter_code` holds any trailing comprehension-style `if` filters
    (`for x in xs if cond`). It's the raw Python source of everything
    after the first top-level ` if `; `None` when no filter is present.
    """

    targets: list[str]
    iter_code: str
    raw_target: str = ""
    filter_code: str | None = None


@dataclass
class ElementNode:
    tag: str
    attrs: list[Attribute]
    children: list = field(default_factory=list)
    self_closing: bool = False
    include_path: str | None = None  # component path — set for PascalCase tags
    offset: int = 0  # body offset of the start tag, for source mapping


@dataclass
class IfBranch:
    """One branch of an `{% if %}` chain. `condition=None` for `{% else %}`."""

    condition: str | None
    children: list = field(default_factory=list)
    offset: int = 0


@dataclass
class IfNode:
    """An `{% if %} … {% elif %} … {% else %} … {% endif %}` chain."""

    branches: list[IfBranch] = field(default_factory=list)
    offset: int = 0


@dataclass
class ForNode:
    """A `{% for %} … {% endfor %}` loop."""

    clause: ForClause
    children: list = field(default_factory=list)
    offset: int = 0


@dataclass
class SlotNode:
    """A `{% slot "name" %} … {% endslot %}` block.

    Caller-side: routes its children into a component's named slot.
    """

    name: str
    children: list = field(default_factory=list)
    offset: int = 0


@dataclass
class TextNode:
    text: str
    offset: int = 0


@dataclass
class ExprNode:
    code: str
    offset: int = 0


@dataclass
class RawNode:
    """The verbatim body of a `{% raw %}` region."""

    text: str
    offset: int = 0


@dataclass
class HtmlCommentNode:
    text: str
    offset: int = 0


@dataclass
class TemplateCommentNode:
    text: str
    offset: int = 0


@dataclass
class DoctypeNode:
    text: str
    offset: int = 0


Node = (
    ElementNode
    | IfNode
    | ForNode
    | SlotNode
    | TextNode
    | ExprNode
    | RawNode
    | HtmlCommentNode
    | TemplateCommentNode
    | DoctypeNode
)


@dataclass
class _Frame:
    """One open scope on the parse stack — an element or a `{% %}` block."""

    kind: str  # "element" | "if" | "for" | "slot"
    children: list[Node]
    element: ElementNode | None = None
    if_node: IfNode | None = None
    saw_else: bool = False
    label: str = ""
    offset: int = 0


def parse(
    tokens: list[Token], *, components: dict[str, str] | None = None
) -> list[Node]:
    components = components or {}
    root: list[Node] = []
    stack: list[_Frame] = []

    def current() -> list[Node]:
        return stack[-1].children if stack else root

    for tok in tokens:
        match tok:
            case TextToken():
                current().append(TextNode(tok.text, offset=tok.offset))
            case ExprToken():
                current().append(ExprNode(tok.code, offset=tok.offset))
            case RawToken():
                current().append(RawNode(tok.text, offset=tok.offset))
            case HtmlCommentToken():
                current().append(HtmlCommentNode(tok.text, offset=tok.offset))
            case TemplateCommentToken():
                current().append(TemplateCommentNode(tok.text, offset=tok.offset))
            case DoctypeToken():
                current().append(DoctypeNode(tok.text, offset=tok.offset))
            case StartTagToken():
                node = _make_element(tok, components)
                current().append(node)
                if not (node.self_closing or node.tag in VOID_ELEMENTS):
                    stack.append(
                        _Frame(
                            "element",
                            node.children,
                            element=node,
                            label=node.tag,
                            offset=tok.offset,
                        )
                    )
            case EndTagToken():
                _close_element(stack, tok)
            case BlockToken():
                _handle_block(tok, stack, root)
            case _:
                raise ParseError(f"Unknown token: {tok!r}")

    if stack:
        frame = stack[-1]
        if frame.kind == "element":
            unclosed = ", ".join(f"<{f.label}>" for f in stack if f.kind == "element")
            raise ParseError(f"Unclosed elements: {unclosed} at offset {frame.offset}")
        raise ParseError(
            f"Unclosed `{{% {frame.label} %}}` block at offset {frame.offset}"
        )
    return root


def _close_element(stack: list[_Frame], tok: EndTagToken) -> None:
    if not stack:
        raise ParseError(
            f"Unexpected </{tok.name}> at offset {tok.offset}: no open element"
        )
    top = stack[-1]
    if top.kind != "element":
        raise ParseError(
            f"</{tok.name}> at offset {tok.offset} closes an element opened "
            f"outside the enclosing `{{% {top.label} %}}` block — a block "
            f"branch must contain balanced HTML"
        )
    assert top.element is not None
    if top.element.tag != tok.name:
        raise ParseError(
            f"Mismatched tag: expected </{top.element.tag}> but got "
            f"</{tok.name}> at offset {tok.offset}"
        )
    stack.pop()


def _handle_block(tok: BlockToken, stack: list[_Frame], root: list[Node]) -> None:
    kind, arg = _classify_block(tok.content, tok.offset)

    def append(node: Node) -> None:
        (stack[-1].children if stack else root).append(node)

    if kind == "if":
        if_node = IfNode(offset=tok.offset)
        branch = IfBranch(condition=arg, offset=tok.offset)
        if_node.branches.append(branch)
        append(if_node)
        stack.append(
            _Frame(
                "if", branch.children, if_node=if_node, label="if", offset=tok.offset
            )
        )
    elif kind in ("elif", "else"):
        if not stack or stack[-1].kind != "if":
            if stack and stack[-1].kind == "element":
                raise ParseError(
                    f"`{{% {kind} %}}` at offset {tok.offset}: <{stack[-1].label}> "
                    f"opened in this branch is not closed"
                )
            raise ParseError(
                f"`{{% {kind} %}}` at offset {tok.offset} without an open `{{% if %}}`"
            )
        frame = stack[-1]
        assert frame.if_node is not None
        if frame.saw_else:
            raise ParseError(
                f"`{{% {kind} %}}` after `{{% else %}}` at offset {tok.offset}"
            )
        if kind == "elif":
            branch = IfBranch(condition=arg, offset=tok.offset)
        else:
            branch = IfBranch(condition=None, offset=tok.offset)
            frame.saw_else = True
        frame.if_node.branches.append(branch)
        frame.children = branch.children
    elif kind == "endif":
        _expect_block_close(stack, "if", tok)
        stack.pop()
    elif kind == "for":
        for_node = ForNode(clause=_parse_for_clause(arg), offset=tok.offset)
        append(for_node)
        stack.append(_Frame("for", for_node.children, label="for", offset=tok.offset))
    elif kind == "endfor":
        _expect_block_close(stack, "for", tok)
        stack.pop()
    elif kind == "slot":
        slot_node = SlotNode(name=_parse_slot_name(arg, tok.offset), offset=tok.offset)
        append(slot_node)
        stack.append(
            _Frame("slot", slot_node.children, label="slot", offset=tok.offset)
        )
    elif kind == "endslot":
        _expect_block_close(stack, "slot", tok)
        stack.pop()


def _expect_block_close(stack: list[_Frame], kind: str, tok: BlockToken) -> None:
    if not stack:
        raise ParseError(
            f"`{{% end{kind} %}}` at offset {tok.offset} without an open "
            f"`{{% {kind} %}}`"
        )
    top = stack[-1]
    if top.kind == "element":
        raise ParseError(
            f"`{{% end{kind} %}}` at offset {tok.offset}: <{top.label}> opened "
            f"inside this block is not closed — a block branch must contain "
            f"balanced HTML"
        )
    if top.kind != kind:
        raise ParseError(
            f"`{{% end{kind} %}}` at offset {tok.offset} closes a "
            f"`{{% {top.label} %}}` block — mismatched"
        )


def _classify_block(content: str, offset: int) -> tuple[str, str]:
    """Return `(keyword, argument)` for a `{% ... %}` tag's content."""
    stripped = content.strip()
    if not stripped:
        raise ParseError(f"empty block tag at offset {offset}")
    parts = stripped.split(None, 1)
    keyword = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    if keyword in ("else", "endif", "endfor", "endslot"):
        if rest:
            raise ParseError(
                f"`{{% {keyword} %}}` takes no arguments at offset {offset}"
            )
        return keyword, ""
    if keyword in ("if", "elif", "for", "slot"):
        if not rest:
            raise ParseError(
                f"`{{% {keyword} %}}` requires an argument at offset {offset}"
            )
        return keyword, rest
    raise ParseError(f"unknown block tag `{{% {keyword} ... %}}` at offset {offset}")


def _parse_slot_name(arg: str, offset: int) -> str:
    s = arg.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    raise ParseError(f"`{{% slot %}}` name must be a quoted string at offset {offset}")


def _make_element(tok: StartTagToken, components: dict[str, str]) -> ElementNode:
    include_path: str | None = None
    if _is_component_tag(tok.name):
        mapped = components.get(tok.name)
        if mapped is None:
            raise ParseError(
                f"unknown component `<{tok.name}>` at offset {tok.offset} — "
                f"add it to the `components:` frontmatter"
            )
        include_path = mapped
    return ElementNode(
        tag=tok.name,
        attrs=list(tok.attrs),
        self_closing=tok.self_closing,
        include_path=include_path,
        offset=tok.offset,
    )


def _is_component_tag(tag: str) -> bool:
    """A component tag is PascalCase: starts with an uppercase letter."""
    return bool(tag) and tag[0].isupper()


def _parse_for_clause(clause: str) -> ForClause:
    """Split `target in iterable [if filter ...]`, returning typed names,
    the iterable expression, and any trailing comprehension `if` filters.

    Splits on the first top-level ` in ` keyword. Handles tuple targets like
    `(i, item) in enumerate(xs)` via parenthesis tracking. After the
    iterable, a top-level ` if ` begins the filter — everything from there
    is `filter_code`. A second top-level ` for ` (a nested loop) is
    rejected.
    """
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
            rest = clause[i + 4 :].strip()
            iter_code, filter_code = _split_for_filter(rest)
            return ForClause(
                targets=_parse_target_names(target),
                iter_code=iter_code,
                raw_target=target,
                filter_code=filter_code,
            )
        i += 1
    raise ParseError(f"`{{% for %}}` clause missing ' in ' separator: {clause!r}")


def _split_for_filter(rest: str) -> tuple[str, str | None]:
    """Split the post-`in` portion into (iterable, filter | None).

    Scans for top-level ` if ` keywords — everything before the first is
    the iterable. Each ` if ` opens a comprehension filter; multiple
    filters (`for x in xs if a if b`) combine into one `filter_code`
    string joined with `and` (the semantics a comprehension gives them).
    A top-level ` for ` (a second loop clause) is a `ParseError`.
    """
    depth = 0
    i = 0
    n = len(rest)
    if_positions: list[int] = []
    while i < n:
        c = rest[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and rest.startswith(" for ", i):
            raise ParseError(
                f"`{{% for %}}` accepts only one `for` clause — nested loops "
                f"are not allowed; nest a second `{{% for %}}` block instead: "
                f"{rest!r}"
            )
        elif depth == 0 and rest.startswith(" if ", i):
            if_positions.append(i)
        i += 1
    if not if_positions:
        return rest, None

    iter_code = rest[: if_positions[0]].strip()
    # Slice out each filter expression (the text between successive `if`
    # keyword boundaries). `+ 4` skips past the ` if ` token.
    filters: list[str] = []
    bounds = if_positions + [n]
    for idx, start in enumerate(if_positions):
        filt = rest[start + 4 : bounds[idx + 1]].strip()
        # Parenthesize each filter so combining with `and` is unambiguous.
        filters.append(f"({filt})" if len(if_positions) > 1 else filt)
    filter_code = " and ".join(filters)
    return iter_code, filter_code


def _parse_target_names(target: str) -> list[str]:
    """Extract one or more names from a `{% for %}` target.

    Single name → one-element list. Tuple unpack (optionally parenthesized) →
    list of names in order.
    """
    t = target.strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    if "," in t:
        return [n.strip() for n in t.split(",") if n.strip()]
    return [t]
