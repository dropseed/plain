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

from plain.forms import fields as form_fields
from plain.schema import Schema


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


def is_schema_class(t: Any) -> bool:
    """Subclasses of `plain.schema.Schema` (excluding the base itself)."""
    return isinstance(t, type) and issubclass(t, Schema) and t is not Schema


_PRIMITIVE_SCHEMAS: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    dict: {"type": "object"},
    list: {"type": "array"},
    UUID: {"type": "string", "format": "uuid"},
}


# Map a Field class to its base OpenAPI schema fragment. Subclasses match
# their ancestor entry — e.g. `EmailField(TextField)` finds the EmailField row
# first; an unknown subclass of `TextField` would fall back to TextField.
_FIELD_SCHEMAS: list[tuple[type[form_fields.Field], dict[str, Any]]] = [
    (form_fields.EmailField, {"type": "string", "format": "email"}),
    (form_fields.URLField, {"type": "string", "format": "uri"}),
    (form_fields.UUIDField, {"type": "string", "format": "uuid"}),
    (form_fields.RegexField, {"type": "string"}),
    (form_fields.TextField, {"type": "string"}),
    (form_fields.IntegerField, {"type": "integer"}),
    (form_fields.FloatField, {"type": "number"}),
    (form_fields.DecimalField, {"type": "number"}),
    (form_fields.DateTimeField, {"type": "string", "format": "date-time"}),
    (form_fields.DateField, {"type": "string", "format": "date"}),
    (form_fields.TimeField, {"type": "string", "format": "time"}),
    (form_fields.DurationField, {"type": "string"}),
    (form_fields.BooleanField, {"type": "boolean"}),
    (form_fields.NullBooleanField, {"type": "boolean", "nullable": True}),
    (form_fields.MultipleChoiceField, {"type": "array", "items": {"type": "string"}}),
    (form_fields.TypedChoiceField, {"type": "string"}),
    (form_fields.ChoiceField, {"type": "string"}),
    (form_fields.JSONField, {"type": "object"}),
    (form_fields.ImageField, {"type": "string", "format": "binary"}),
    (form_fields.FileField, {"type": "string", "format": "binary"}),
]


def schema_from_field(field: form_fields.Field) -> dict[str, Any]:
    """Translate a single forms Field instance to an OpenAPI property schema.

    Picks the base schema by Field class and folds in declared constraints
    (max_length / min_length, max_value / min_value, choices, regex pattern).
    """
    base: dict[str, Any] = {}
    for field_cls, fragment in _FIELD_SCHEMAS:
        if isinstance(field, field_cls):
            base = dict(fragment)
            break

    # Length / range constraints
    if (max_length := getattr(field, "max_length", None)) is not None:
        base["maxLength"] = max_length
    if (min_length := getattr(field, "min_length", None)) is not None:
        base["minLength"] = min_length
    if (max_value := getattr(field, "max_value", None)) is not None:
        base["maximum"] = max_value
    if (min_value := getattr(field, "min_value", None)) is not None:
        base["minimum"] = min_value

    # Regex pattern (RegexField subclasses)
    if regex := getattr(field, "regex", None):
        pattern = getattr(regex, "pattern", None)
        if isinstance(pattern, str):
            base["pattern"] = pattern

    # Enumerated choices — only for plain ChoiceField, not Multiple
    if isinstance(field, form_fields.ChoiceField) and not isinstance(
        field, form_fields.MultipleChoiceField
    ):
        choices = getattr(field, "choices", None)
        if choices:
            base["enum"] = [value for value, _label in choices]

    return base


def _schema_class_body(
    schema_cls: type[Schema],
    *,
    components: dict[str, Any] | None,
) -> dict[str, Any]:
    """Render a Schema subclass body — `properties` from fields, `required` list from required flags."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, field in schema_cls._schema_fields.items():
        properties[name] = schema_from_field(field)
        if field.required:
            required.append(name)

    body: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        body["required"] = required
    return body


def schema_from_type(
    t: Any,
    *,
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate a Python type to an OpenAPI schema. With `components`, register TypedDicts/Schemas there and return `$ref`s; without, inline them."""
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

    if is_schema_class(t):
        if components is not None:
            schemas = components.setdefault("schemas", {})
            name = t.__name__
            if name not in schemas:
                schemas[name] = {}
                schemas[name] = _schema_class_body(t, components=components)
            return {"$ref": f"#/components/schemas/{name}"}
        return _schema_class_body(t, components=None)

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
    """Return the first TypedDict or Schema class found in `annotation`, walking unions like `MyDict | Response | None`."""
    if is_typed_dict(annotation) or is_schema_class(annotation):
        return annotation

    if get_origin(annotation) in (Union, UnionType):
        for arg in get_args(annotation):
            if arg is NoneType:
                continue
            if is_typed_dict(arg) or is_schema_class(arg):
                return arg
    return None
