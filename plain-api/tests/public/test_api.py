from typing import Literal, TypedDict

from plain.api import openapi
from plain.api.openapi.generator import OpenAPISchemaGenerator
from plain.api.openapi.utils import schema_from_type
from plain.api.openapi.validation import validate_openapi_schema
from plain.api.views import APIKeyView, APIView
from plain.schema import Schema, types
from plain.test import Client
from plain.urls import Router, path


def test_api_view():
    client = Client()
    response = client.get("/test")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, world!"}


def test_typed_dict_return_value_serializes_as_json():
    """A view returning a TypedDict instance should serialize as a JSON object."""
    client = Client()
    response = client.get("/typed-dict-return")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, typed!"}


def test_tuple_status_code_return_overrides_default_200():
    """`return (status_code, body)` should set the response status code."""
    client = Client()
    response = client.post("/tuple-status-return")
    assert response.status_code == 201
    assert response.json() == {"id": 42, "created": True}


def test_versioned_api_view():
    client = Client()
    response = client.post(
        "/test-versioned",
        headers={"API-Version": "v2"},
        data={"name": "Dave"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, Dave!"}

    response = client.post(
        "/test-versioned",
        headers={"API-Version": "v1"},
        data={"to": "Dave"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json() == {"msg": "Hello, Dave!"}


def test_validation_error_is_returned_as_400_json():
    """ValidationError must convert to a JSON 400 regardless of error shape.

    Single-string errors expose `.message`; field-dict and list errors only
    expose `.messages`. The handler must cover both without crashing into a
    500. Field-dict errors get a structured `errors` list so clients can
    render per-field feedback.
    """
    client = Client()

    response = client.post(
        "/validation-error",
        data={"shape": "string"},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["id"] == "validation_error"
    assert body["message"].startswith("Validation error: ")
    assert "errors" not in body

    response = client.post(
        "/validation-error",
        data={"shape": "list"},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["id"] == "validation_error"
    assert body["message"].startswith("Validation error: ")
    assert "errors" not in body

    response = client.post(
        "/validation-error",
        data={"shape": "dict"},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["id"] == "validation_error"
    assert body["message"] == "Validation error"
    assert body["errors"] == [
        {"field": "password", "message": "This field is required."}
    ]


def test_unsupported_media_type_is_returned_as_415_json():
    """A non-JSON Content-Type on a json_data view must surface as 415, not 500.

    Before the change, `request.json_data` raised `ValueError`, which fell
    through to the catch-all 500. Now `UnsupportedMediaTypeError415` flows
    through `handle_exception` as a clean 415 with a stable error id.
    """
    client = Client()

    response = client.post(
        "/json-echo",
        data="hello",
        content_type="text/plain",
    )
    assert response.status_code == 415
    body = response.json()
    assert body["id"] == "unsupported_media_type"


def test_openapi_only_emits_operations_for_implemented_methods():
    """Class-level 2xx schema on a get-only view must not emit POST/PUT/etc.

    `View` provides runtime stubs for every handler, so `getattr(cls, "post")`
    would find one even when the subclass never implemented POST. The generator
    must gate on `implemented_methods`, not attribute presence.
    """

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class GetOnlyView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("only-get", GetOnlyView, name="only_get")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    operations = schema["paths"]["/only-get"]
    assert set(operations) == {"get"}


def test_openapi_path_params_translated_for_both_url_forms():
    """Both `<type:name>` and shorthand `<name>` translate to OpenAPI's `{name}`."""

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class IssueView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [
            path("explicit/<int:pk>/", IssueView, name="explicit"),
            path("shorthand/<slug>/", IssueView, name="shorthand"),
            path("mixed/<int:pk>/<slug>/", IssueView, name="mixed"),
        ]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    paths = set(schema["paths"].keys())
    assert paths == {
        "/explicit/{pk}/",
        "/shorthand/{slug}/",
        "/mixed/{pk}/{slug}/",
    }


def test_path_params_use_native_openapi_types():
    """Built-in URL converters should emit their natural JSON Schema type.

    Spec consumers (codegen, fuzzers like schemathesis) treat
    `type: integer` differently from `type: string with pattern`. Plain's
    built-in converters carry that information, so the generator should
    surface it.
    """

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class TargetView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [
            path("by-int/<int:pk>/", TargetView, name="by_int"),
            path("by-uuid/<uuid:id>/", TargetView, name="by_uuid"),
            path("by-slug/<slug:tag>/", TargetView, name="by_slug"),
            path("by-str/<str:name>/", TargetView, name="by_str"),
        ]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    by_name = {
        path: op["get"]["parameters"][0]["schema"]
        for path, op in schema["paths"].items()
    }
    assert by_name["/by-int/{pk}/"] == {"type": "integer"}
    assert by_name["/by-uuid/{id}/"] == {"type": "string", "format": "uuid"}
    assert by_name["/by-slug/{tag}/"]["type"] == "string"
    assert by_name["/by-slug/{tag}/"]["pattern"]
    assert by_name["/by-str/{name}/"]["type"] == "string"


def test_operation_id_defaults_from_view_class_and_method():
    """Each operation gets a stable operationId so spec consumers can chain it.

    OpenAPI links, generated client SDKs, and tools like schemathesis all key
    off operationId. We default it from the view class name (rather than the
    URL `name=`) because URL names exist for `reverse()` and get renamed
    during refactors — view class names are far more stable.
    """

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class CrudView(APIView):
        def get(self):
            return {"ok": True}

        def post(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = "api"
        urls = [path("notes/", CrudView, name="notes_list")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    operations = schema["paths"]["/notes/"]
    assert operations["get"]["operationId"] == "CrudView_get"
    assert operations["post"]["operationId"] == "CrudView_post"


def test_operation_id_can_be_overridden():
    """User-supplied operationId in @openapi.schema wins over the default."""

    class CustomView(APIView):
        @openapi.schema(
            {
                "operationId": "fetchEverything",
                "responses": {"200": {"description": "ok"}},
            }
        )
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("things/", CustomView, name="things_list")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    assert schema["paths"]["/things/"]["get"]["operationId"] == "fetchEverything"


def test_openapi_helpers_build_content_and_body_envelopes():
    """`openapi.json_content` and `openapi.json_body` produce the standard envelopes."""
    schema_ref = {"$ref": "#/components/schemas/X"}
    assert openapi.json_content(schema_ref) == {
        "application/json": {"schema": schema_ref}
    }
    assert openapi.json_body(schema_ref) == {
        "required": True,
        "content": {"application/json": {"schema": schema_ref}},
    }
    assert openapi.json_body(schema_ref, required=False) == {
        "required": False,
        "content": {"application/json": {"schema": schema_ref}},
    }


def test_link_to_targets_default_operation_id():
    """`openapi.link_to(view, ...)` matches the framework-default operationId."""

    class TargetView(APIView):
        def get(self):
            return None

    assert openapi.link_to(TargetView, parameters={"id": "$response.body#/id"}) == {
        "operationId": "TargetView_get",
        "parameters": {"id": "$response.body#/id"},
    }
    assert openapi.link_to(
        TargetView, method="patch", parameters={"id": "$response.body#/id"}
    ) == {
        "operationId": "TargetView_patch",
        "parameters": {"id": "$response.body#/id"},
    }


def test_json_not_found_view_returns_json_404_for_any_method():
    """`JsonNotFoundView` is a catch-all that yields a JSON ErrorSchema 404."""
    client = Client()

    response = client.get("/missing-anything")
    assert response.status_code == 404
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.json()["id"] == "not_found"

    response = client.post(
        "/missing-anything", data="{}", content_type="application/json"
    )
    assert response.status_code == 404
    assert response.json()["id"] == "not_found"


def test_api_key_view_auto_emits_security_scheme():
    """`APIKeyView` subclasses get `securitySchemes.BearerAuth` and per-op `security`."""

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class SecureView(APIView, APIKeyView):
        def get_api_key(self):
            return None

        def use_api_key(self):
            pass

        def get(self):
            return {"ok": True}

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class PublicView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [
            path("secure/", SecureView, name="secure"),
            path("public/", PublicView, name="public"),
        ]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert schema["paths"]["/secure/"]["get"]["security"] == [{"BearerAuth": []}]
    assert "security" not in schema["paths"]["/public/"]["get"]


def test_generated_schema_validates_against_openapi_spec():
    """Generated specs must validate against the OpenAPI 3 JSON Schema."""

    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "An item",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            }
        }
    )
    class ItemView(APIView):
        def get(self):
            return {"id": self.url_kwargs["id"]}

    @openapi.schema(
        {
            "openapi": "3.0.3",
            "info": {"title": "Test API", "version": "1.0.0"},
        }
    )
    class APIRouter(Router):
        namespace = ""
        urls = [path("items/<int:id>", ItemView, name="item")]

    schema = OpenAPISchemaGenerator(APIRouter()).schema
    validate_openapi_schema(schema)


def test_schema_from_type_literal_string_emits_enum():
    assert schema_from_type(Literal["recent", "slowest", "errored"]) == {
        "type": "string",
        "enum": ["recent", "slowest", "errored"],
    }


def test_schema_from_type_literal_int_emits_enum():
    assert schema_from_type(Literal[1, 2, 3]) == {
        "type": "integer",
        "enum": [1, 2, 3],
    }


def test_schema_from_type_literal_mixed_falls_back_to_bare_enum():
    assert schema_from_type(Literal["a", 1]) == {"enum": ["a", 1]}


def test_schema_from_type_dict_emits_additional_properties():
    class Activity(TypedDict):
        signal: str
        count: int

    assert schema_from_type(dict[str, Activity]) == {
        "type": "object",
        "additionalProperties": {
            "type": "object",
            "properties": {
                "signal": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
    }


def test_schema_from_type_resolves_forward_ref_annotations():
    """String-form annotations (from `from __future__ import annotations`) resolve via `get_type_hints`."""
    Wrapper = TypedDict("Wrapper", {"items": "list[int]", "name": "str"})  # noqa: UP013

    assert schema_from_type(Wrapper) == {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "integer"}},
            "name": {"type": "string"},
        },
    }


def test_path_params_auto_merged_with_declared_query_params():
    @openapi.schema(
        {
            "parameters": [
                {
                    "name": "since",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {"200": {"description": "ok"}},
        }
    )
    class WindowedView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("apps/<slug>/insights/", WindowedView, name="insights")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    params = schema["paths"]["/apps/{slug}/insights/"]["get"]["parameters"]
    by_key = {(p["name"], p["in"]): p for p in params}
    assert ("slug", "path") in by_key
    assert by_key[("slug", "path")]["required"] is True
    assert ("since", "query") in by_key


def test_declared_path_param_overrides_auto_extracted():
    @openapi.schema(
        {
            "parameters": [
                {
                    "name": "slug",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Tenant slug",
                }
            ],
            "responses": {"200": {"description": "ok"}},
        }
    )
    class CustomView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("things/<slug>/", CustomView, name="thing")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    params = schema["paths"]["/things/{slug}/"]["get"]["parameters"]
    slug_params = [p for p in params if p["name"] == "slug" and p["in"] == "path"]
    assert len(slug_params) == 1
    assert slug_params[0]["description"] == "Tenant slug"


def test_return_annotation_drives_200_response_schema():
    class ItemResponse(TypedDict):
        id: int
        name: str

    class ItemView(APIView):
        def get(self) -> ItemResponse:
            return {"id": 1, "name": "x"}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("items/", ItemView, name="items")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/items/"]["get"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ItemResponse"
    }
    assert schema["components"]["schemas"]["ItemResponse"] == {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
        },
    }


def test_nested_typed_dicts_register_as_separate_components():
    """Nested TypedDicts each get their own `components.schemas` entry, parent uses `$ref`."""

    class Item(TypedDict):
        id: int
        name: str

    class ItemList(TypedDict):
        items: list[Item]
        total: int

    class V(APIView):
        def get(self) -> ItemList:
            return {"items": [], "total": 0}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("items/", V, name="items")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    schemas = schema["components"]["schemas"]
    assert "ItemList" in schemas
    assert "Item" in schemas
    # Parent references the child by $ref instead of inlining its shape.
    assert schemas["ItemList"]["properties"]["items"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/Item"},
    }
    assert schemas["Item"] == {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }


def test_nested_typed_dict_via_dict_value_registers():
    """A TypedDict used as a `dict` value also gets registered and `$ref`d."""

    class Activity(TypedDict):
        signal: str
        count: int

    class ActivityMap(TypedDict):
        apps: dict[str, Activity]

    class V(APIView):
        def get(self) -> ActivityMap:
            return {"apps": {}}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("activity/", V, name="activity")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    schemas = schema["components"]["schemas"]
    assert "Activity" in schemas
    assert schemas["ActivityMap"]["properties"]["apps"] == {
        "type": "object",
        "additionalProperties": {"$ref": "#/components/schemas/Activity"},
    }


def test_return_annotation_extracts_typed_dict_from_union_with_response():
    from plain.http import Response

    class Item(TypedDict):
        id: int

    class ItemView(APIView):
        def get(self) -> Item | Response:
            return {"id": 1}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("items/", ItemView, name="items")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    ref = schema["paths"]["/items/"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert ref == {"$ref": "#/components/schemas/Item"}


def test_return_annotation_does_not_override_explicit_decorator():
    class FromDecorator(TypedDict):
        kind: str

    class FromAnnotation(TypedDict):
        kind: str
        extra: int

    @openapi.response_typed_dict(200, FromDecorator)
    class Mixed(APIView):
        def get(self) -> FromAnnotation:
            return FromAnnotation(kind="x", extra=1)

    class LocalRouter(Router):
        namespace = ""
        urls = [path("things/", Mixed, name="things")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    ref = schema["paths"]["/things/"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert ref == {"$ref": "#/components/schemas/FromDecorator"}


def test_method_docstring_becomes_summary_and_description():
    class HasDoc(TypedDict):
        ok: bool

    class V(APIView):
        def get(self) -> HasDoc:
            """List notes for the current user.

            Returns the most recent 50 notes ordered by `created_at` DESC.
            Excludes archived notes — use `?archived=1` to include them.
            """
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("notes/", V, name="notes")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/notes/"]["get"]
    assert op["summary"] == "List notes for the current user."
    assert op["description"].startswith("Returns the most recent 50 notes")


def test_method_docstring_wrapped_summary_paragraph_joined():
    class HasDoc(TypedDict):
        ok: bool

    class V(APIView):
        def get(self) -> HasDoc:
            """Returns the authenticated user plus the teams they belong to.
            Used by the CLI to confirm a token works.
            """
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("me/", V, name="me")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/me/"]["get"]
    assert op["summary"] == (
        "Returns the authenticated user plus the teams they belong to. "
        "Used by the CLI to confirm a token works."
    )
    assert "description" not in op


def test_class_docstring_used_when_method_has_none():
    class HasDoc(TypedDict):
        ok: bool

    class V(APIView):
        """Single-line view doc."""

        def get(self) -> HasDoc:
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("v/", V, name="v")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/v/"]["get"]
    assert op["summary"] == "Single-line view doc."
    assert "description" not in op


def test_leading_http_method_line_is_dropped_from_docstring():
    class HasDoc(TypedDict):
        ok: bool

    class V(APIView):
        def get(self) -> HasDoc:
            """GET /things/

            Real summary is here.

            And the description follows.
            """
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("things/", V, name="things")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/things/"]["get"]
    assert op["summary"] == "Real summary is here."
    assert op["description"] == "And the description follows."


def test_explicit_summary_overrides_docstring():
    class HasDoc(TypedDict):
        ok: bool

    @openapi.schema({"summary": "Custom summary"})
    class V(APIView):
        def get(self) -> HasDoc:
            """Docstring summary that should lose."""
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("x/", V, name="x")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/x/"]["get"]
    assert op["summary"] == "Custom summary"


def test_openapi_parameters_class_attribute_walked_via_mro():
    class WindowedView(APIView):
        openapi_parameters = [
            {
                "name": "since",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            }
        ]

    class Item(TypedDict):
        ok: bool

    class ItemView(WindowedView):
        openapi_parameters = [
            {
                "name": "name",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
            }
        ]

        def get(self) -> Item:
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("ts/<slug>/", ItemView, name="ts")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    params = schema["paths"]["/ts/{slug}/"]["get"]["parameters"]
    by_key = {(p["name"], p["in"]): p for p in params}
    assert ("slug", "path") in by_key
    assert ("since", "query") in by_key
    assert ("name", "query") in by_key


def test_include_view_filter_drops_excluded_views():
    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class PublicView(APIView):
        accepts_api_key = True

        def get(self):
            return {"ok": True}

    @openapi.schema({"responses": {"200": {"description": "ok"}}})
    class InternalView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [
            path("public/", PublicView, name="public"),
            path("internal/", InternalView, name="internal"),
        ]

    class PublicOnlyGenerator(OpenAPISchemaGenerator):
        def include_view(self, view_class):
            return getattr(view_class, "accepts_api_key", False)

    schema = PublicOnlyGenerator(LocalRouter()).schema
    assert "/public/" in schema["paths"]
    assert "/internal/" not in schema["paths"]


def test_ref_parameters_merge_alongside_path_params():
    """A `$ref` parameter has no `name`/`in`; merging must key it by the ref string."""

    @openapi.schema(
        {
            "parameters": [{"$ref": "#/components/parameters/Limit"}],
            "responses": {"200": {"description": "ok"}},
        }
    )
    class ListView(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("items/<int:pk>/", ListView, name="items")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    params = schema["paths"]["/items/{pk}/"]["get"]["parameters"]
    assert {"$ref": "#/components/parameters/Limit"} in params
    assert any(p.get("name") == "pk" and p.get("in") == "path" for p in params)


def test_response_typed_dict_decorator_emits_named_component():
    class Item(TypedDict):
        id: int
        name: str

    class ItemView(APIView):
        @openapi.response_typed_dict(200, Item)
        def get(self):
            return {"id": 1, "name": "x"}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("items/", ItemView, name="items")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    op = schema["paths"]["/items/"]["get"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Item"
    }
    assert schema["components"]["schemas"]["Item"] == {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }


def test_response_typed_dict_decorator_walks_nested_typed_dicts():
    """Nested TypedDicts referenced via the decorator should each register as their own component."""

    class Inner(TypedDict):
        value: int

    class Outer(TypedDict):
        inner: Inner

    class V(APIView):
        @openapi.response_typed_dict(200, Outer)
        def get(self):
            return {"inner": {"value": 1}}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("v/", V, name="v")]

    schemas = OpenAPISchemaGenerator(LocalRouter()).schema["components"]["schemas"]
    assert "Outer" in schemas
    assert "Inner" in schemas
    assert schemas["Outer"]["properties"]["inner"] == {
        "$ref": "#/components/schemas/Inner"
    }


def test_inline_responses_via_schema_decorator_pass_through():
    """An inline `responses` block on `@openapi.schema` is emitted verbatim."""

    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "Custom",
                    "content": openapi.json_content({"type": "object"}),
                }
            }
        }
    )
    class V(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("v/", V, name="v")]

    op = OpenAPISchemaGenerator(LocalRouter()).schema["paths"]["/v/"]["get"]
    assert op["responses"]["200"]["description"] == "Custom"
    assert op["responses"]["200"]["content"] == openapi.json_content({"type": "object"})


def test_view_without_any_response_declaration_is_dropped():
    """A view with no 2xx/3xx response declared should not appear in `paths`."""

    class V(APIView):
        def get(self):
            return {"ok": True}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("nothing/", V, name="nothing")]

    paths = OpenAPISchemaGenerator(LocalRouter()).schema["paths"]
    assert "/nothing/" not in paths


def test_return_annotation_fills_in_200_when_schema_decorator_only_sets_summary():
    """`@openapi.schema({"summary": ...})` + `-> Item` → annotation supplies the 200."""

    class Item(TypedDict):
        id: int

    @openapi.schema({"summary": "List items"})
    class V(APIView):
        def get(self) -> Item:
            return {"id": 1}

    class LocalRouter(Router):
        namespace = ""
        urls = [path("items/", V, name="items")]

    op = OpenAPISchemaGenerator(LocalRouter()).schema["paths"]["/items/"]["get"]
    assert op["summary"] == "List items"
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Item"
    }


# ---------------------------------------------------------------------------
# plain.schema.Schema integration
# ---------------------------------------------------------------------------


def test_schema_from_type_emits_object_with_properties_and_required():
    class S(Schema):
        title: str = types.TextField(max_length=200, min_length=1)
        notes: str | None = types.TextField(required=False, max_length=2000)
        count: int = types.IntegerField(min_value=0, max_value=100)

    assert schema_from_type(S) == {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 200, "minLength": 1},
            "notes": {"type": "string", "maxLength": 2000},
            "count": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["title", "count"],
    }


def test_schema_choice_field_emits_enum():
    class S(Schema):
        priority: str = types.ChoiceField(choices=[("low", "Low"), ("high", "High")])

    assert schema_from_type(S)["properties"]["priority"] == {
        "type": "string",
        "enum": ["low", "high"],
    }


def test_schema_email_url_uuid_get_format_hints():
    class S(Schema):
        email: str = types.EmailField()
        site: str = types.URLField()

    props = schema_from_type(S)["properties"]
    assert props["email"] == {"type": "string", "format": "email"}
    assert props["site"] == {"type": "string", "format": "uri"}


def test_schema_registers_as_component_when_components_passed():
    class TaskInput(Schema):
        title: str = types.TextField(max_length=100)

    components: dict = {}
    ref = schema_from_type(TaskInput, components=components)
    assert ref == {"$ref": "#/components/schemas/TaskInput"}
    assert components["schemas"]["TaskInput"] == {
        "type": "object",
        "properties": {"title": {"type": "string", "maxLength": 100}},
        "required": ["title"],
    }


def test_schema_return_annotation_drives_200_response():
    class TaskOut(Schema):
        title: str = types.TextField()

    class V(APIView):
        def get(self) -> TaskOut:
            return TaskOut(title="x")

    class LocalRouter(Router):
        namespace = ""
        urls = [path("tasks/", V, name="tasks")]

    schema = OpenAPISchemaGenerator(LocalRouter()).schema
    assert schema["paths"]["/tasks/"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/TaskOut"}
    assert schema["components"]["schemas"]["TaskOut"]["properties"]["title"] == {
        "type": "string"
    }


def test_schema_body_helper_builds_request_body():
    class TaskInput(Schema):
        title: str = types.TextField(max_length=200)

    body = openapi.schema_body(TaskInput)
    assert body == {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string", "maxLength": 200}},
                    "required": ["title"],
                }
            }
        },
    }
