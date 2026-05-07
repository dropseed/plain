import json
from typing import Any

from plain.urls import Router, URLPattern, URLResolver
from plain.urls.converters import (
    IntConverter,
    UUIDConverter,
    _get_converters,
)

from .utils import merge_data


def _build_operation_id(view_class: type, method: str) -> str:
    return f"{view_class.__name__}_{method}"


def _schema_for_converter(converter: Any) -> dict[str, Any]:
    if isinstance(converter, IntConverter):
        return {"type": "integer"}
    if isinstance(converter, UUIDConverter):
        return {"type": "string", "format": "uuid"}
    return {"type": "string", "pattern": converter.regex}


def _security_schemes_for_view(view_class: type) -> dict[str, dict[str, Any]]:
    """Collect `openapi_security_schemes` declared on a view's MRO."""
    schemes: dict[str, dict[str, Any]] = {}
    for cls in reversed(view_class.__mro__):
        declared = cls.__dict__.get("openapi_security_schemes")
        if declared:
            schemes.update(declared)
    return schemes


class OpenAPISchemaGenerator:
    def __init__(self, router: Router):
        self.url_converters = {
            class_instance.__class__: key
            for key, class_instance in _get_converters().items()
        }

        # Get initial schema from the router
        self.schema = getattr(router, "openapi_schema", {}).copy()
        self.components = getattr(router, "openapi_components", {}).copy()

        self.schema["paths"] = self.get_paths(router.urls)

        if self.components:
            self.schema["components"] = self.components

    def as_json(self, indent: int) -> str:
        return json.dumps(self.schema, indent=indent, sort_keys=True)

    def as_yaml(self, indent: int) -> str:
        import yaml

        # Don't want to get anchors when we dump...
        cleaned = json.loads(self.as_json(indent=0))
        return yaml.safe_dump(cleaned, indent=indent, sort_keys=True)

    def get_paths(
        self,
        urls: list[URLPattern | URLResolver],
    ) -> dict[str, dict[str, Any]]:
        paths = {}

        for url_pattern in urls:
            if isinstance(url_pattern, URLResolver):
                paths.update(self.get_paths(url_pattern.url_patterns))
            elif isinstance(url_pattern, URLPattern):
                if operations := self.operations_for_url_pattern(url_pattern):
                    path = self.path_from_url_pattern(url_pattern, "/")
                    # TODO could have class level summary/description?
                    paths[path] = operations
            else:
                raise ValueError(f"Unknown url pattern: {url_pattern}")

        return paths

    def path_from_url_pattern(self, url_pattern: URLPattern, root_path: str) -> str:
        path = root_path + str(url_pattern.pattern)

        for name, converter in url_pattern.pattern.converters.items():
            key = self.url_converters[converter.__class__]
            # Handle both `<type:name>` and the `<name>` shorthand for the default `str` converter.
            path = path.replace(f"<{key}:{name}>", f"{{{name}}}")
            path = path.replace(f"<{name}>", f"{{{name}}}")
        return path

    def extract_components(self, obj: Any) -> None:
        """
        Extract components from a view or router.
        """
        if hasattr(obj, "openapi_components"):
            self.components = merge_data(
                self.components,
                getattr(obj, "openapi_components", {}),
            )

    def operations_for_url_pattern(
        self,
        url_pattern: URLPattern,
    ) -> dict[str, Any]:
        operations = {}

        # `View` defines runtime stubs for every handler, so gating on
        # `implemented_methods` is what tells us which verbs the leaf class
        # actually handles (vs. inheriting a stub that will 405).
        implemented = getattr(
            url_pattern.view_class, "implemented_methods", frozenset()
        )

        for vc in reversed(url_pattern.view_class.__mro__):
            for method in implemented:
                class_method = vc.__dict__.get(method)
                if not class_method:
                    continue

                operation = {}

                # Get anything on from the view class itself,
                # then override it with the method-specific data
                self.extract_components(vc)
                operation = merge_data(
                    operation,
                    getattr(vc, "openapi_schema", {}),
                )

                # Get the schema that applies to the specific method
                self.extract_components(class_method)
                operation = merge_data(
                    operation,
                    getattr(class_method, "openapi_schema", {}),
                )

                # Get URL parameters if nothing else was defined
                if operation and "parameters" not in operation:
                    if parameters := self.parameters_from_url_patterns([url_pattern]):
                        operation["parameters"] = parameters

                if operation and "operationId" not in operation:
                    operation["operationId"] = _build_operation_id(
                        url_pattern.view_class, method
                    )

                if operation and "security" not in operation:
                    schemes = _security_schemes_for_view(url_pattern.view_class)
                    if schemes:
                        operation["security"] = [{name: []} for name in schemes]
                        self.components = merge_data(
                            self.components,
                            {"securitySchemes": schemes},
                        )

                # If there are no responses in the 2XX or 3XX range, then don't return it at all.
                # Most likely the developer didn't define any actual responses for their endpoint,
                # and all we did was inherit the base error responses.
                keep_operation = False
                for status_code in operation.get("responses", {}).keys():
                    if status_code.startswith("2") or status_code.startswith("3"):
                        keep_operation = True
                        break

                if operation and keep_operation:
                    if method in operations:
                        # Merge operation with existing data
                        operations[method] = merge_data(operations[method], operation)
                    else:
                        operations[method] = operation

        return operations

    def parameters_from_url_patterns(
        self, url_patterns: list[URLPattern]
    ) -> list[dict[str, Any]]:
        """Need to process any parent/included url patterns too"""
        parameters = []

        for url_pattern in url_patterns:
            for name, converter in url_pattern.pattern.converters.items():
                parameters.append(
                    {
                        "name": name,
                        "in": "path",
                        "required": True,
                        "schema": _schema_for_converter(converter),
                    }
                )

        return parameters
