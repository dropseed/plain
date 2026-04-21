"""Derive JSON Schema from a Tool's `__init__` signature + type hints."""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin, get_type_hints

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

_PRIMITIVE_TO_JSON_SCHEMA: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def build_input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Derive a JSON Schema `object` from `fn`'s type hints.

    Supports primitives (str/int/float/bool), `list[T]`, `dict`, `T | None`,
    `Literal[...]`, and falls back to permissive `string` for anything else.
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except (NameError, TypeError):
        # Unresolvable forward refs or un-inspectable signatures: fall
        # back to no hints and let every param default to string.
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        # Missing annotation → `Any` (permissive string), not `type(None)`.
        hint = hints.get(param_name, Any)
        prop, is_optional = _type_to_schema(hint)
        properties[param_name] = prop

        has_default = param.default is not inspect.Parameter.empty
        if not has_default and not is_optional:
            required.append(param_name)

    schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DIALECT,
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _type_to_schema(hint: Any) -> tuple[dict[str, Any], bool]:
    if hint is type(None):
        return {"type": "null"}, True
    if hint is Any or hint is inspect.Parameter.empty:
        return {"type": "string"}, False
    if isinstance(hint, type) and hint in _PRIMITIVE_TO_JSON_SCHEMA:
        return {"type": _PRIMITIVE_TO_JSON_SCHEMA[hint]}, False

    origin = get_origin(hint)
    args = get_args(hint)

    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        has_none = len(non_none) < len(args)
        branches = [_type_to_schema(a)[0] for a in non_none]
        # Keep the None branch in the schema — clients need it to know an
        # explicit `null` is accepted. `is_optional` separately tells the
        # outer builder not to mark the field required.
        if has_none:
            branches.append({"type": "null"})
        if len(branches) == 1:
            return branches[0], has_none
        return {"anyOf": branches}, has_none

    if origin is Literal:
        enum_values = list(args)
        schema: dict[str, Any] = {"enum": enum_values}
        primitive_types = {
            p
            for v in enum_values
            if (p := _PRIMITIVE_TO_JSON_SCHEMA.get(type(v))) is not None
        }
        if len(primitive_types) == 1:
            schema["type"] = primitive_types.pop()
        return schema, False

    if origin in (list, tuple, set, frozenset) or hint in (
        list,
        tuple,
        set,
        frozenset,
    ):
        items = _type_to_schema(args[0])[0] if args else {}
        return {"type": "array", "items": items}, False

    if origin is dict or hint is dict:
        return {"type": "object"}, False

    return {"type": "string"}, False
