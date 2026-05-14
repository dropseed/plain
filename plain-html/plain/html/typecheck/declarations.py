"""Typed view over a template's frontmatter declarations.

The plain frontmatter parser hands back YAML primitives — strings, dicts,
lists. For type checking we need stronger structure: each `attrs:` entry
becomes a (type-expression, default-expression?) pair; each `imports:`
line becomes a validated Python import statement; each `slots:` entry
becomes a required/optional + optional `yields:` type.

Validation happens here so the synthesis layer can assume well-formed
inputs. Errors raise `DeclarationError` with a human-readable message.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


class DeclarationError(Exception):
    pass


@dataclass
class AttrDeclaration:
    """One entry in `attrs:` — name, type-expression source, default-expression source."""

    name: str
    type_source: str
    default_source: str | None
    required: bool
    doc: str | None = None


@dataclass
class SlotDeclaration:
    """One entry in `slots:` — name, required, optional `yields:` type-expression source."""

    name: str
    required: bool
    yields_source: str | None


@dataclass
class ImportDeclaration:
    """One entry in `imports:` — the raw `import` / `from ... import ...` source."""

    statement: str


@dataclass
class Declarations:
    attrs: list[AttrDeclaration]
    imports: list[ImportDeclaration]
    slots: list[SlotDeclaration]


def parse(frontmatter: dict) -> Declarations:
    """Read raw YAML data, return validated declarations.

    The frontmatter dict is what `python-frontmatter` produces. Missing
    sections are treated as empty.
    """
    return Declarations(
        attrs=_parse_attrs(frontmatter.get("attrs") or {}),
        imports=_parse_imports(frontmatter.get("imports") or []),
        slots=_parse_slots(frontmatter.get("slots") or {}),
    )


def _parse_attrs(raw: object) -> list[AttrDeclaration]:
    if not isinstance(raw, dict):
        raise DeclarationError(
            f"`attrs:` must be a mapping of name → type, got {type(raw).__name__}"
        )
    out: list[AttrDeclaration] = []
    for name, value in raw.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise DeclarationError(f"`attrs:` keys must be identifiers, got {name!r}")
        out.append(_parse_attr_value(name, value))
    return out


def _parse_attr_value(name: str, value: Any) -> AttrDeclaration:
    if isinstance(value, str):
        type_source, default_source = _split_inline_attr(value)
        return AttrDeclaration(
            name=name,
            type_source=type_source,
            default_source=default_source,
            required=default_source is None,
        )
    if isinstance(value, dict):
        if "type" not in value:
            raise DeclarationError(
                f"Expanded `attrs:` entry {name!r} requires a `type:` field"
            )
        type_source = _validate_type_expression(name, str(value["type"]))
        default_source: str | None = None
        if "default" in value:
            default_source = _validate_default_expression(
                name, _yaml_to_python_literal(value["default"])
            )
        required_field = value.get("required")
        if required_field is None:
            required = default_source is None
        else:
            required = bool(required_field)
        doc = value.get("doc")
        if doc is not None and not isinstance(doc, str):
            raise DeclarationError(
                f"`attrs.{name}.doc` must be a string, got {type(doc).__name__}"
            )
        return AttrDeclaration(
            name=name,
            type_source=type_source,
            default_source=default_source,
            required=required,
            doc=doc,
        )
    raise DeclarationError(
        f"`attrs:` entry {name!r} must be a string or mapping, got {type(value).__name__}"
    )


def _split_inline_attr(raw: str) -> tuple[str, str | None]:
    """Parse `<type-expr>` or `<type-expr> = <default-expr>`.

    Reuses Python's annotated-assignment grammar by reparsing as
    `_dummy: <raw>` (or `_dummy: <type> = <default>`), which gives clean
    AST nodes for both halves.
    """
    raw = raw.strip()
    if not raw:
        raise DeclarationError("attr type expression cannot be empty")

    try:
        module = ast.parse(f"_dummy: {raw}", mode="exec")
    except SyntaxError as exc:
        raise DeclarationError(f"Invalid attr declaration {raw!r}: {exc.msg}") from exc

    if len(module.body) != 1 or not isinstance(module.body[0], ast.AnnAssign):
        raise DeclarationError(f"Invalid attr declaration {raw!r}")

    node = module.body[0]
    type_source = ast.unparse(node.annotation)
    default_source = ast.unparse(node.value) if node.value is not None else None
    return type_source, default_source


def _validate_type_expression(name: str, raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise DeclarationError(f"attr {name!r} has an empty type expression")
    try:
        node = ast.parse(raw, mode="eval")
    except SyntaxError as exc:
        raise DeclarationError(
            f"Invalid type expression for attr {name!r}: {exc.msg}"
        ) from exc
    return ast.unparse(node.body)


def _validate_default_expression(name: str, raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise DeclarationError(f"attr {name!r} has an empty default expression")
    try:
        node = ast.parse(raw, mode="eval")
    except SyntaxError as exc:
        raise DeclarationError(
            f"Invalid default expression for attr {name!r}: {exc.msg}"
        ) from exc
    return ast.unparse(node.body)


def _yaml_to_python_literal(value: object) -> str:
    """Convert a YAML scalar back into a Python source-literal string.

    Expanded-form defaults arrive as already-parsed YAML (string, int,
    bool, None, list, dict). For type checking we need the equivalent
    Python source. Strings round-trip via repr; everything else via str.
    """
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_to_python_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        items = (
            f"{_yaml_to_python_literal(k)}: {_yaml_to_python_literal(v)}"
            for k, v in value.items()
        )
        return "{" + ", ".join(items) + "}"
    raise DeclarationError(
        f"Cannot represent default value of type {type(value).__name__}"
    )


def _parse_imports(raw: object) -> list[ImportDeclaration]:
    if not isinstance(raw, list):
        raise DeclarationError(
            f"`imports:` must be a list of import statements, got {type(raw).__name__}"
        )
    out: list[ImportDeclaration] = []
    for item in raw:
        if not isinstance(item, str):
            raise DeclarationError(
                f"`imports:` entries must be strings, got {type(item).__name__}"
            )
        statement = item.strip()
        try:
            module = ast.parse(statement, mode="exec")
        except SyntaxError as exc:
            raise DeclarationError(
                f"Invalid import statement {statement!r}: {exc.msg}"
            ) from exc
        if len(module.body) != 1 or not isinstance(
            module.body[0], ast.Import | ast.ImportFrom
        ):
            raise DeclarationError(
                f"`imports:` entry must be a single import statement, got {statement!r}"
            )
        out.append(ImportDeclaration(statement=statement))
    return out


def _parse_slots(raw: object) -> list[SlotDeclaration]:
    if not isinstance(raw, dict):
        raise DeclarationError(f"`slots:` must be a mapping, got {type(raw).__name__}")
    out: list[SlotDeclaration] = []
    for name, value in raw.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise DeclarationError(f"`slots:` keys must be identifiers, got {name!r}")
        out.append(_parse_slot_value(name, value))
    return out


def _parse_slot_value(name: str, value: Any) -> SlotDeclaration:
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "required":
            return SlotDeclaration(name=name, required=True, yields_source=None)
        if token == "optional":
            return SlotDeclaration(name=name, required=False, yields_source=None)
        raise DeclarationError(
            f"`slots.{name}` must be 'required' or 'optional', got {value!r}"
        )
    if isinstance(value, dict):
        required_field = value.get("required")
        required = bool(required_field) if required_field is not None else False
        yields_source: str | None = None
        if "yields" in value:
            yields_source = _validate_type_expression(
                f"slots.{name}.yields", str(value["yields"])
            )
        return SlotDeclaration(
            name=name, required=required, yields_source=yields_source
        )
    raise DeclarationError(
        f"`slots:` entry {name!r} must be a string or mapping, got {type(value).__name__}"
    )
