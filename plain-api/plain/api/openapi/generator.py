import inspect
import json
import re
from typing import Any, get_type_hints

from plain.urls import Router, URLPattern, URLResolver

from .helpers import json_content
from .utils import merge_data, schema_from_type, typed_dict_from_annotation

# A leading `GET /path/` line in a docstring is dropped — the URL is already in `paths`.
_LEADING_HTTP_METHOD = re.compile(
    r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S+\s*$",
    re.IGNORECASE,
)


def _merge_parameters(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge parameter lists by `(name, in)` (or `$ref`). Later sources override earlier ones."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        for p in source:
            key = ("$ref", p["$ref"]) if "$ref" in p else (p["name"], p["in"])
            by_key[key] = p
    return list(by_key.values())


def _build_operation_id(view_class: type, method: str) -> str:
    return f"{view_class.__name__}_{method}"


def _schema_for_converter(converter: Any) -> dict[str, Any]:
    if converter.keyword == "int":
        return {"type": "integer"}
    if converter.keyword == "uuid":
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


def _parameters_for_view(view_class: type) -> list[dict[str, Any]]:
    """Walk MRO collecting `openapi_parameters`; descendants override by `(name, in)`."""
    return _merge_parameters(
        *(
            cls.__dict__.get("openapi_parameters") or []
            for cls in reversed(view_class.__mro__)
        )
    )


def _docstring_summary_description(
    class_method: Any,
    view_class: type,
) -> dict[str, str]:
    """PEP 257 split: first paragraph → `summary`, rest → `description`. Falls back to the view class."""
    doc = (inspect.getdoc(class_method) or inspect.getdoc(view_class) or "").strip()
    if not doc:
        return {}

    first, _, rest = doc.partition("\n")
    if _LEADING_HTTP_METHOD.match(first.strip()):
        doc = rest.lstrip()

    summary, _, description = doc.partition("\n\n")
    summary = " ".join(summary.split())
    description = description.strip()

    out: dict[str, str] = {}
    if summary:
        out["summary"] = summary
    if description:
        out["description"] = description
    return out


class OpenAPISchemaGenerator:
    def __init__(self, router: Router):
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
        path = root_path + url_pattern.raw_route

        for name, converter in url_pattern.route.converters.items():
            # Handle both `<type:name>` and the `<name>` shorthand for the default `str` converter.
            path = path.replace(f"<{converter.keyword}:{name}>", f"{{{name}}}")
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

    def include_view(self, view_class: type) -> bool:
        """Override to drop a view from the schema."""
        return True

    def _response_from_return_annotation(
        self, class_method: Any
    ) -> dict[str, Any] | None:
        """Build a 200 response fragment from the method's return annotation if it points at a TypedDict."""
        try:
            hints = get_type_hints(class_method)
        except Exception:
            return None

        return_type = hints.get("return")
        if return_type is None:
            return None

        typed_dict = typed_dict_from_annotation(return_type)
        if typed_dict is None:
            return None

        top_ref = schema_from_type(typed_dict, components=self.components)
        return {
            "responses": {
                "200": {
                    "description": "OK",
                    "content": json_content(top_ref),
                }
            }
        }

    def operations_for_url_pattern(
        self,
        url_pattern: URLPattern,
    ) -> dict[str, Any]:
        operations: dict[str, Any] = {}

        if not self.include_view(url_pattern.view_class):
            return operations

        # `View` defines runtime stubs for every handler, so gating on
        # `implemented_methods` is what tells us which verbs the leaf class
        # actually handles (vs. inheriting a stub that will 405).
        implemented = getattr(
            url_pattern.view_class, "implemented_methods", frozenset()
        )

        inherited_params = _parameters_for_view(url_pattern.view_class)
        auto_params = self.parameters_from_url_patterns([url_pattern])
        schemes = _security_schemes_for_view(url_pattern.view_class)

        for vc in reversed(url_pattern.view_class.__mro__):
            self.extract_components(vc)
            for method in implemented:
                class_method = vc.__dict__.get(method)
                if not class_method:
                    continue

                self.extract_components(class_method)
                operation = merge_data(
                    getattr(vc, "openapi_schema", {}),
                    getattr(class_method, "openapi_schema", {}),
                )

                already_has_2xx = any(
                    code.startswith("2") for code in operation.get("responses", {})
                )
                if not already_has_2xx:
                    inferred = self._response_from_return_annotation(class_method)
                    if inferred is not None:
                        operation = merge_data(operation, inferred)

                for key, value in _docstring_summary_description(
                    class_method, vc
                ).items():
                    operation.setdefault(key, value)

                if not operation:
                    continue

                merged_params = _merge_parameters(
                    auto_params,
                    inherited_params,
                    list(operation.get("parameters", [])),
                )
                if merged_params:
                    operation["parameters"] = merged_params

                operation.setdefault(
                    "operationId",
                    _build_operation_id(url_pattern.view_class, method),
                )

                if "security" not in operation and schemes:
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
            for name, converter in url_pattern.route.converters.items():
                parameters.append(
                    {
                        "name": name,
                        "in": "path",
                        "required": True,
                        "schema": _schema_for_converter(converter),
                    }
                )

        return parameters
