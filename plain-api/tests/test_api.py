from plain.api import openapi
from plain.api.openapi.generator import OpenAPISchemaGenerator
from plain.api.openapi.validation import validate_openapi_schema
from plain.api.views import APIView
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


def test_generated_schema_validates_against_openapi_spec():
    """Generated specs must validate against the OpenAPI 3 JSON Schema."""

    @openapi.schema(
        {
            "openapi": "3.0.3",
            "info": {"title": "Test API", "version": "1.0.0"},
        }
    )
    class APIRouter(Router):
        namespace = ""
        urls = [
            path(
                "items/<int:id>",
                _decorated_item_view(),
                name="item",
            ),
        ]

    schema = OpenAPISchemaGenerator(APIRouter()).schema
    validate_openapi_schema(schema)


def _decorated_item_view():
    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "An item",
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                        }
                    },
                }
            }
        }
    )
    class ItemView(APIView):
        def get(self):
            return {"id": self.url_kwargs["id"]}

    return ItemView
