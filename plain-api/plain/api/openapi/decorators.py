from collections.abc import Callable
from http import HTTPStatus
from typing import Any, TypeVar

from .helpers import json_content
from .utils import merge_data, schema_from_type

F = TypeVar("F", bound=Callable[..., Any])


def response_typed_dict(
    status_code: int | HTTPStatus | str,
    return_type: Any,
    *,
    description: str = "",
    component_name: str = "",
) -> Callable[[F], F]:
    """A decorator to attach responses to a view method."""

    def decorator(func: F) -> F:
        # TODO if return_type is a list/tuple,
        # then use anyOf or oneOf?

        response_schema: dict[str, Any] = {
            "description": description or HTTPStatus(int(status_code)).phrase,
        }

        if return_type:
            registry: dict[str, Any] = {}
            top_ref = schema_from_type(return_type, components=registry)
            response_schema["content"] = json_content(top_ref)
            func.openapi_components = merge_data(
                getattr(func, "openapi_components", {}),
                registry,
            )

        if component_name:
            _schema = {
                "responses": {
                    str(status_code): {
                        "$ref": f"#/components/responses/{component_name}"
                    }
                }
            }
            func.openapi_components = merge_data(
                getattr(func, "openapi_components", {}),
                {
                    "responses": {
                        component_name: response_schema,
                    }
                },
            )
        else:
            _schema = {"responses": {str(status_code): response_schema}}

        # Add the response schema to the function
        func.openapi_schema = merge_data(
            getattr(func, "openapi_schema", {}),
            _schema,
        )

        return func

    return decorator


def schema(data: dict[str, Any]) -> Callable[[F], F]:
    """Attach raw OpenAPI schema to a router, view, or view method."""

    def decorator(func: F) -> F:
        func.openapi_schema = merge_data(
            getattr(func, "openapi_schema", {}),
            data,
        )
        return func

    return decorator
