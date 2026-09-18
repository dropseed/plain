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
    `Literal[...]`, and falls back to a permissive empty schema (accepts any
    JSON value) for anything else.
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except (NameError, TypeError):
        # Unresolvable forward refs or un-inspectable signatures: fall back to
        # no hints so every param defaults to the permissive empty schema —
        # never a strict type we'd then wrongly reject valid arguments against.
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        # `*args` / `**kwargs` aren't named arguments a client supplies — a
        # `**kwargs` tool accepts arbitrary extra args. Advertising the synthetic
        # `args`/`kwargs` name as a (required) property would make validation
        # reject every real call (`missing required argument: kwargs`).
        if param.kind in (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            continue

        # Missing annotation → `Any` → permissive empty schema, not `type(None)`.
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


_TYPE_DESCRIPTIONS = {
    "string": "a string",
    "integer": "an integer",
    "number": "a number",
    "boolean": "a boolean",
    "array": "an array",
    "object": "an object",
    "null": "null",
}


def validate_arguments(schema: dict[str, Any], arguments: Any) -> list[str]:
    """Check `tools/call` arguments against a generated input schema.

    Returns a list of human-readable error messages (empty when valid), so a
    bad argument becomes a clear, model-fixable tool error instead of an opaque
    "Tool execution failed" once `run()` chokes on it (SEP-1303).

    Only the JSON Schema keywords `build_input_schema` emits are checked —
    `type`, `properties`, `required`, `enum`, `anyOf`, `items`. Any other
    construct (a hand-written `input_schema` using `oneOf`, `$ref`, `pattern`,
    numeric bounds, …) is treated permissively, so we never need a full JSON
    Schema validator (or a new dependency) and never falsely reject a schema we
    don't fully model.
    """
    if not isinstance(arguments, dict):
        return ["must be an object"]
    if not isinstance(schema, dict):
        # Misconfigured tool (non-dict input_schema) — can't validate against it,
        # so stay permissive and let tool_cls(**arguments) handle arity.
        schema = {}

    errors: list[str] = []

    required = schema.get("required")
    for name in required if isinstance(required, list) else ():
        if name not in arguments:
            errors.append(f"missing required argument: {name}")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    for name, value in arguments.items():
        prop = properties.get(name)
        # Unmodeled property (schema declares no properties, or additional args
        # a hand-written schema doesn't list) — a genuinely unexpected kwarg is
        # still rejected by the `tool_cls(**arguments)` TypeError downstream.
        if prop is None:
            continue
        if error := _validate_value(name, value, prop):
            errors.append(error)

    return errors


def _validate_value(name: str, value: Any, schema: Any) -> str | None:
    # Malformed or unmodeled schema fragment (e.g. a hand-written `input_schema`
    # with a shorthand string property value) — stay permissive, never crash.
    if not isinstance(schema, dict):
        return None

    enum = schema.get("enum")
    if isinstance(enum, list):
        if any(_enum_matches(value, member) for member in enum):
            return None
        return f"'{name}' must be {_describe_type(schema)}"

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        if any(_validate_value(name, value, b) is None for b in any_of):
            return None
        return f"'{name}' must be {_describe_branches(any_of)}"

    json_type = schema.get("type")
    if json_type is None:
        # No keyword we understand constrains this value — stay permissive.
        return None
    if not _matches_json_type(value, json_type):
        return f"'{name}' must be {_describe_type(schema)}"

    if json_type == "array" and "items" in schema:
        # Past the type check above, so `value` is a list. Aggregate every bad
        # element so the model can fix them in one round-trip.
        items_schema = schema["items"]
        item_errors = [
            error
            for index, item in enumerate(value)
            if (error := _validate_value(f"{name}[{index}]", item, items_schema))
        ]
        if item_errors:
            return "; ".join(item_errors)
    return None


def _enum_matches(value: Any, member: Any) -> bool:
    # `value in enum` would use `==`, and Python's `bool` is an int subclass, so
    # `True == 1` — but JSON booleans and numbers are distinct types. Reject a
    # bool/non-bool mismatch, while keeping numeric `1 == 1.0` equality and
    # str/int Enum members comparing equal to their serialized value.
    if isinstance(value, bool) != isinstance(member, bool):
        return False
    return value == member


def _matches_json_type(value: Any, json_type: str) -> bool:
    # `bool` is a subclass of `int` in Python, but JSON `true`/`false` is not an
    # integer/number and `1` is not a boolean — check bool explicitly both ways.
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "integer":
        if isinstance(value, bool):
            return False
        # `5.0` is a valid integer per JSON Schema 2020-12 (integer is defined
        # by value, not representation) — and LLM clients commonly emit it.
        return isinstance(value, int) or (
            isinstance(value, float) and value.is_integer()
        )
    if json_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    if json_type == "null":
        return value is None
    # Unknown type keyword from a hand-written schema — permissive.
    return True


def _describe_type(schema: dict[str, Any]) -> str:
    """Human phrase for what a schema fragment accepts (for error messages)."""
    # Guard `enum` as a list to match `_validate_value` — a malformed non-list
    # enum must not crash message building into a logged INTERNAL_ERROR.
    enum = schema.get("enum")
    if isinstance(enum, list):
        return "one of: " + ", ".join(str(v) for v in enum)
    if json_type := schema.get("type"):
        return _TYPE_DESCRIPTIONS.get(json_type, json_type)
    return "a valid value"


def _describe_branches(branches: list[dict[str, Any]]) -> str:
    return " or ".join(_describe_type(b) for b in branches) or "a valid value"


def _type_to_schema(hint: Any) -> tuple[dict[str, Any], bool]:
    # Whatever keyword shapes this emits must stay understood by `_validate_value`
    # / `_matches_json_type` — an emitted shape the validator doesn't model is
    # silently under-validated. Add a new case here → add its handling there.
    if hint is type(None):
        return {"type": "null"}, True
    if hint is Any or hint is inspect.Parameter.empty:
        # Unknown type — advertise no constraint (accepts anything) rather than
        # a strict `string` the validator would then wrongly enforce.
        return {}, False
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

    # Unrecognized type — permissive empty schema, same rationale as `Any`.
    return {}, False
