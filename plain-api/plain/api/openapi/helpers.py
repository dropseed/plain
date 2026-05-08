from __future__ import annotations

from typing import Any

from plain.schema import Schema

from .utils import schema_from_type


def json_content(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a schema in OpenAPI's `application/json` content envelope."""
    return {"application/json": {"schema": schema}}


def json_body(schema: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    """Build an `application/json` requestBody for the given schema."""
    return {"required": required, "content": json_content(schema)}


def schema_content(
    schema_cls: type[Schema],
    *,
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a `plain.schema.Schema` class in an `application/json` content envelope.

    Pass the same `components` dict you give to the router to register the
    schema as a reusable component and return a `$ref`. Omit it to inline.
    """
    return json_content(schema_from_type(schema_cls, components=components))


def schema_body(
    schema_cls: type[Schema],
    *,
    required: bool = True,
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an `application/json` requestBody from a `plain.schema.Schema` class."""
    return {
        "required": required,
        "content": schema_content(schema_cls, components=components),
    }


def link_to(
    view_class: type, *, parameters: dict[str, str], method: str = "get"
) -> dict[str, Any]:
    """Build an OpenAPI link to another view's operation.

    Targets the framework-default operationId — `{ViewClass}_{method}`. Pass
    parameter expressions as values, e.g. `{"id": "$response.body#/id"}`.
    """
    return {
        "operationId": f"{view_class.__name__}_{method}",
        "parameters": parameters,
    }
