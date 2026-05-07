from plain.api import openapi
from plain.api.openapi.generator import OpenAPISchemaGenerator
from plain.api.openapi.validation import validate_openapi_schema
from plain.api.views import APIKeyView, APIView
from plain.test import Client
from plain.urls import Router, path


def test_api_view():
    client = Client()
    response = client.get("/test")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, world!"}


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
