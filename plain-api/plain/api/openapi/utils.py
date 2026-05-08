from types import NoneType, UnionType
from typing import (
    Any,
    Literal,
    NotRequired,
    Required,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID


def merge_data(data1: dict[str, Any], data2: dict[str, Any]) -> dict[str, Any]:
    merged = data1.copy()
    for key, value in data2.items():
        if key in merged:
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = merge_data(merged[key], value)
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged


def is_typed_dict(t: Any) -> bool:
    """TypedDict classes carry `__required_keys__` / `__optional_keys__` set by the metaclass."""
    return (
        isinstance(t, type)
        and hasattr(t, "__required_keys__")
        and hasattr(t, "__optional_keys__")
    )


_PRIMITIVE_SCHEMAS: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    dict: {"type": "object"},
    list: {"type": "array"},
    UUID: {"type": "string", "format": "uuid"},
}


def schema_from_type(
    t: Any,
    *,
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate a Python type to an OpenAPI schema. With `components`, register TypedDicts there and return `$ref`s; without, inline them."""
    if get_origin(t) in (NotRequired, Required):
        return schema_from_type(get_args(t)[0], components=components)

    if get_origin(t) is Literal:
        values = list(get_args(t))
        value_types = {type(v) for v in values}
        if value_types == {str}:
            return {"type": "string", "enum": values}
        if value_types == {int}:
            return {"type": "integer", "enum": values}
        if value_types == {bool}:
            return {"type": "boolean", "enum": values}
        return {"enum": values}

    if is_typed_dict(t):
        if components is not None:
            schemas = components.setdefault("schemas", {})
            name = t.__name__
            if name not in schemas:
                # Placeholder breaks self-referential cycles.
                schemas[name] = {}
                schemas[name] = _typed_dict_body(t, components=components)
            return {"$ref": f"#/components/schemas/{name}"}
        return _typed_dict_body(t, components=None)

    if hasattr(t, "__origin__"):
        if t.__origin__ is list:
            return {
                "type": "array",
                "items": schema_from_type(t.__args__[0], components=components),
            }
        elif t.__origin__ is dict:
            return {
                "type": "object",
                "additionalProperties": schema_from_type(
                    t.__args__[1], components=components
                ),
            }
        else:
            raise ValueError(f"Unknown type: {t}")

    if hasattr(t, "__args__") and len(t.__args__) == 2 and type(None) in t.__args__:
        return {
            **schema_from_type(t.__args__[0], components=components),
            "nullable": True,
        }

    schema = _PRIMITIVE_SCHEMAS.get(t) or _PRIMITIVE_SCHEMAS.get(t.__class__)
    if schema is None:
        raise ValueError(f"Unknown type: {t}")
    return dict(schema)


def _typed_dict_body(
    t: Any,
    *,
    components: dict[str, Any] | None,
) -> dict[str, Any]:
    """Render a TypedDict body; `get_type_hints` resolves string-form annotations."""
    try:
        hints = get_type_hints(t, include_extras=True)
    except Exception:
        hints = t.__annotations__
    return {
        "type": "object",
        "properties": {
            k: schema_from_type(v, components=components) for k, v in hints.items()
        },
    }


def typed_dict_from_annotation(annotation: Any) -> type | None:
    """Return the first TypedDict found in `annotation`, walking unions like `MyDict | Response | None`."""
    if is_typed_dict(annotation):
        return annotation

    if get_origin(annotation) in (Union, UnionType):
        for arg in get_args(annotation):
            if arg is NoneType:
                continue
            if is_typed_dict(arg):
                return arg
    return None
