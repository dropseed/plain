from typing import Any
from uuid import UUID


def merge_data(data1, data2):
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


def schema_from_type(t) -> dict[str, Any]:
    # if it's a union with None, add nullable: true

    # if t has a comment, add description
    # import inspect
    # if description := inspect.getdoc(t):
    #     extra_fields = {"description": description}
    # else:
    extra_fields: dict[str, Any] = {}

    if hasattr(t, "__annotations__") and t.__annotations__:
        # It's a TypedDict...
        return {
            "type": "object",
            "properties": {
                k: schema_from_type(v) for k, v in t.__annotations__.items()
            },
            **extra_fields,
        }

    if hasattr(t, "__origin__"):
        if t.__origin__ is list:
            return {
                "type": "array",
                "items": schema_from_type(t.__args__[0]),
                **extra_fields,
            }
        elif t.__origin__ is dict:
            return {
                "type": "object",
                "properties": {
                    k: schema_from_type(v)
                    for k, v in t.__args__[1].__annotations__.items()
                },
                **extra_fields,
            }
        else:
            raise ValueError(f"Unknown type: {t}")

    if hasattr(t, "__args__") and len(t.__args__) == 2 and type(None) in t.__args__:
        return {
            **schema_from_type(t.__args__[0]),
            "nullable": True,
            **extra_fields,
        }

    type_mappings: dict[Any, dict] = {
        str: {
            "type": "string",
        },
        int: {
            "type": "integer",
        },
        float: {
            "type": "number",
        },
        bool: {
            "type": "boolean",
        },
        dict: {
            "type": "object",
        },
        list: {
            "type": "array",
        },
        UUID: {
            "type": "string",
            "format": "uuid",
        },
    }

    schema = type_mappings.get(t, {})
    if not schema:
        schema = type_mappings.get(t.__class__, {})
        if not schema:
            raise ValueError(f"Unknown type: {t}")

    return {**schema, **extra_fields}
