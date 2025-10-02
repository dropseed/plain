from collections.abc import Callable
from http import HTTPStatus
from typing import Any, TypeVar

from plain.forms import fields
from plain.forms.forms import BaseForm

from .utils import merge_data, schema_from_type

F = TypeVar("F", bound=Callable[..., Any])


def response_typed_dict(
    status_code: int | HTTPStatus | str,
    return_type: Any,
    *,
    description: str = "",
    component_name: str = "",
) -> Callable[[F], F]:
    """
    A decorator to attach responses to a view method.
    """

    def decorator(func: F) -> F:
        # TODO if return_type is a list/tuple,
        # then use anyOf or oneOf?

        response_schema = {
            "description": description or HTTPStatus(int(status_code)).phrase,
        }

        # If we have a return_type, then make it a component and add it
        # to the response and components
        if return_type:
            return_component_name = return_type.__name__
            response_schema["content"] = {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{return_component_name}"}
                }
            }
            _component_schema = {
                "schemas": {
                    return_component_name: schema_from_type(return_type),
                },
            }
            func.openapi_components = merge_data(  # type: ignore[attr-defined]
                getattr(func, "openapi_components", {}),
                _component_schema,
            )

        if component_name:
            _schema = {
                "responses": {
                    str(status_code): {
                        "$ref": f"#/components/responses/{component_name}"
                    }
                }
            }
            func.openapi_components = merge_data(  # type: ignore[attr-defined]
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
        func.openapi_schema = merge_data(  # type: ignore[attr-defined]
            getattr(func, "openapi_schema", {}),
            _schema,
        )

        return func

    return decorator


def request_form(form_class: type[BaseForm]) -> Callable[[F], F]:
    """
    Create OpenAPI parameters from a form class.
    """

    def decorator(func: F) -> F:
        field_mappings = {
            fields.IntegerField: {
                "type": "integer",
            },
            fields.FloatField: {
                "type": "number",
            },
            fields.DateTimeField: {
                "type": "string",
                "format": "date-time",
            },
            fields.DateField: {
                "type": "string",
                "format": "date",
            },
            fields.TimeField: {
                "type": "string",
                "format": "time",
            },
            fields.EmailField: {
                "type": "string",
                "format": "email",
            },
            fields.URLField: {
                "type": "string",
                "format": "uri",
            },
            fields.UUIDField: {
                "type": "string",
                "format": "uuid",
            },
            fields.DecimalField: {
                "type": "number",
            },
            # fields.FileField: {
            #     "type": "string",
            #     "format": "binary",
            # },
            fields.ImageField: {
                "type": "string",
                "format": "binary",
            },
            fields.BooleanField: {
                "type": "boolean",
            },
            fields.CharField: {
                "type": "string",
            },
            fields.EmailField: {
                "type": "string",
                "format": "email",
            },
        }
        _schema = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {},
                        }
                    }
                    # could add application/x-www-form-urlencoded?
                }
            }
        }

        required_fields = []

        for field_name, field in form_class.base_fields.items():  # type: ignore[attr-defined]
            field_schema = field_mappings[field.__class__].copy()
            _schema["requestBody"]["content"]["application/json"]["schema"][
                "properties"
            ][field_name] = field_schema

            if field.required:
                required_fields.append(field_name)

            # TODO add description to the schema
            # TODO add example to the schema
            # TODO add default to the schema

        if required_fields:
            _schema["requestBody"]["content"]["application/json"]["schema"][
                "required"
            ] = required_fields
            # The body is required if any field is
            _schema["requestBody"]["required"] = True

        func.openapi_schema = merge_data(  # type: ignore[attr-defined]
            getattr(func, "openapi_schema", {}),
            _schema,
        )

        return func

    return decorator


def schema(data: dict[str, Any]) -> Callable[[F], F]:
    """
    A decorator to attach raw OpenAPI schema to a router, view, or view method.
    """

    def decorator(func: F) -> F:
        func.openapi_schema = merge_data(  # type: ignore[attr-defined]
            getattr(func, "openapi_schema", {}),
            data,
        )
        return func

    return decorator
