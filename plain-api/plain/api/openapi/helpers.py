from __future__ import annotations

from typing import Any


def json_content(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a schema in OpenAPI's `application/json` content envelope."""
    return {"application/json": {"schema": schema}}


def json_body(schema: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    """Build an `application/json` requestBody for the given schema."""
    return {"required": required, "content": json_content(schema)}


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
