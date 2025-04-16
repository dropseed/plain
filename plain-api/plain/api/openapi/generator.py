import json
from http import HTTPMethod
from typing import Any

from plain.urls import Router, URLPattern, URLResolver
from plain.urls.converters import get_converters

from .utils import merge_data


class OpenAPISchemaGenerator:
    def __init__(self, router: Router):
        self.url_converters = {
            class_instance.__class__: key
            for key, class_instance in get_converters().items()
        }

        # Get initial schema from the router
        self.schema = getattr(router, "openapi_schema", {}).copy()
        self.components = getattr(router, "openapi_components", {}).copy()

        self.schema["paths"] = self.get_paths(router.urls)

        if self.components:
            self.schema["components"] = self.components

    def as_json(self, indent):
        return json.dumps(self.schema, indent=indent, sort_keys=True)

    def as_yaml(self, indent):
        import yaml

        # Don't want to get anchors when we dump...
        cleaned = json.loads(self.as_json(indent=0))
        return yaml.safe_dump(cleaned, indent=indent, sort_keys=True)

    def get_paths(self, urls) -> dict[str, dict[str, Any]]:
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

    def path_from_url_pattern(self, url_pattern, root_path) -> str:
        path = root_path + str(url_pattern.pattern)

        for name, converter in url_pattern.pattern.converters.items():
            key = self.url_converters[converter.__class__]
            path = path.replace(f"<{key}:{name}>", f"{{{name}}}")
        return path

    def extract_components(self, obj):
        """
        Extract components from a view or router.
        """
        if hasattr(obj, "openapi_components"):
            self.components = merge_data(
                self.components,
                getattr(obj, "openapi_components", {}),
            )

    def operations_for_url_pattern(self, url_pattern) -> dict[str, Any]:
        operations = {}

        for vc in reversed(url_pattern.view.view_class.__mro__):
            exclude_http_methods = [
                HTTPMethod.TRACE,
                HTTPMethod.OPTIONS,
                HTTPMethod.CONNECT,
            ]

            for method in [
                x.lower() for x in HTTPMethod if x not in exclude_http_methods
            ]:
                class_method = getattr(vc, method, None)
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

    def parameters_from_url_patterns(self, url_patterns) -> list[dict[str, Any]]:
        """Need to process any parent/included url patterns too"""
        parameters = []

        for url_pattern in url_patterns:
            for name, converter in url_pattern.pattern.converters.items():
                parameters.append(
                    {
                        "name": name,
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "pattern": converter.regex,
                            # "format": "uuid",
                        },
                    }
                )

        return parameters
