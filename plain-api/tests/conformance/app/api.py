"""OpenAPI conformance fixture for plain-api.

Compact API surface that exercises the OpenAPI features schemathesis cares
about: path converters (`<int:>`, `<uuid:>`), required header parameters,
bearer-token auth, API versioning, full CRUD with `links`, and components
(`schemas`/`parameters`/`responses`) referenced via `$ref`. No DB — uses an
in-memory dict store so the fixture runs with zero environment setup.
"""

from __future__ import annotations

import uuid
from itertools import count
from typing import Any

from plain.api import openapi
from plain.api.versioning import APIVersionChange, VersionedAPIView
from plain.api.views import APIKeyView, APIView, JsonNotFoundView
from plain.http import BadRequestError400, JsonResponse, NotFoundError404, Response
from plain.urls import Router, path

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

# The `run` script passes `--header "Authorization: Bearer conformance-key"`
# to schemathesis so any secured operation it generates is accepted.
CONFORMANCE_API_KEY = "conformance-key"

_VALID_KEY_SENTINEL = object()


class ConformanceAPIKeyView(APIKeyView):
    """Authenticates against the hardcoded key, no `APIKey` model required."""

    def get_api_key(self) -> Any:
        header_value = self.request.headers.get("Authorization", "")
        token = header_value.removeprefix("Bearer ")
        if token != CONFORMANCE_API_KEY or token == header_value:
            return None
        return _VALID_KEY_SENTINEL

    def use_api_key(self) -> None:
        return None


# ---------------------------------------------------------------------------
# In-memory note store
# ---------------------------------------------------------------------------

_NOTES: dict[int, dict[str, Any]] = {}
_NEXT_ID = count(1)


def _make_note(title: str, body: str) -> dict[str, Any]:
    note_id = next(_NEXT_ID)
    note = {"id": note_id, "title": title, "body": body}
    _NOTES[note_id] = note
    return note


# Seed a single note so list/detail responses are non-empty on a cold start.
_make_note("Seed", "Seeded by the conformance fixture")


def _read_note_input(payload: dict[str, Any], *, require_title: bool) -> dict[str, str]:
    """Validate a NoteInput/NotePatch body, raising BadRequestError400 on bad input."""
    cleaned: dict[str, str] = {}

    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip():
            raise BadRequestError400("Invalid title")
        cleaned["title"] = title[:200]
    elif require_title:
        raise BadRequestError400("Missing title")

    if "body" in payload:
        body = payload["body"]
        if not isinstance(body, str):
            raise BadRequestError400("Invalid body")
        cleaned["body"] = body

    return cleaned


# ---------------------------------------------------------------------------
# Notes CRUD
# ---------------------------------------------------------------------------


class NoteDetailAPIView(APIView):
    def _get_note(self) -> dict[str, Any]:
        note = _NOTES.get(self.url_kwargs["id"])
        if note is None:
            raise NotFoundError404
        return note

    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "A single note.",
                    "content": openapi.json_content(
                        {"$ref": "#/components/schemas/Note"}
                    ),
                },
            }
        }
    )
    def get(self):
        return self._get_note()

    @openapi.schema(
        {
            "requestBody": openapi.json_body(
                {"$ref": "#/components/schemas/NoteInput"}
            ),
            "responses": {
                "200": {
                    "description": "The replaced note.",
                    "content": openapi.json_content(
                        {"$ref": "#/components/schemas/Note"}
                    ),
                },
            },
        }
    )
    def put(self):
        note = self._get_note()
        cleaned = _read_note_input(self.request.json_data, require_title=True)
        note["title"] = cleaned["title"]
        note["body"] = cleaned.get("body", "")
        return note

    @openapi.schema(
        {
            "requestBody": openapi.json_body(
                {"$ref": "#/components/schemas/NotePatch"}
            ),
            "responses": {
                "200": {
                    "description": "The patched note.",
                    "content": openapi.json_content(
                        {"$ref": "#/components/schemas/Note"}
                    ),
                },
            },
        }
    )
    def patch(self):
        note = self._get_note()
        cleaned = _read_note_input(self.request.json_data, require_title=False)
        if "title" in cleaned:
            note["title"] = cleaned["title"]
        if "body" in cleaned:
            note["body"] = cleaned["body"]
        return note

    @openapi.schema({"responses": {"204": {"description": "Note deleted."}}})
    def delete(self):
        note = self._get_note()
        _NOTES.pop(note["id"], None)
        return Response(status_code=204)


@openapi.schema(
    {
        "parameters": [
            {"$ref": "#/components/parameters/Limit"},
            {
                "name": "q",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Filter notes whose title contains this substring.",
            },
        ],
    }
)
class NoteListAPIView(APIView):
    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "A page of notes.",
                    "content": openapi.json_content(
                        {
                            "type": "object",
                            "required": ["results"],
                            "properties": {
                                "results": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Note"},
                                }
                            },
                        }
                    ),
                },
            }
        }
    )
    def get(self):
        notes = list(_NOTES.values())

        if q := self.request.query_params.get("q"):
            notes = [n for n in notes if q.lower() in n["title"].lower()]

        limit_raw = self.request.query_params.get("limit", "25")
        try:
            limit = max(1, min(int(limit_raw), 100))
        except (TypeError, ValueError):
            raise BadRequestError400("Invalid `limit`")

        return {"results": notes[:limit]}

    @openapi.schema(
        {
            "requestBody": openapi.json_body(
                {"$ref": "#/components/schemas/NoteInput"}
            ),
            "responses": {
                "201": {
                    "description": "The created note.",
                    "headers": {
                        "Location": {
                            "description": "URL of the created note.",
                            "schema": {"type": "string"},
                        }
                    },
                    "content": openapi.json_content(
                        {"$ref": "#/components/schemas/Note"}
                    ),
                    # Lets schemathesis chain POST → CRUD against real ids
                    # instead of randomized 404s.
                    "links": {
                        "GetById": openapi.link_to(
                            NoteDetailAPIView,
                            parameters={"id": "$response.body#/id"},
                        ),
                        "ReplaceById": openapi.link_to(
                            NoteDetailAPIView,
                            method="put",
                            parameters={"id": "$response.body#/id"},
                        ),
                        "PatchById": openapi.link_to(
                            NoteDetailAPIView,
                            method="patch",
                            parameters={"id": "$response.body#/id"},
                        ),
                        "DeleteById": openapi.link_to(
                            NoteDetailAPIView,
                            method="delete",
                            parameters={"id": "$response.body#/id"},
                        ),
                    },
                },
            },
        }
    )
    def post(self):
        cleaned = _read_note_input(self.request.json_data, require_title=True)
        note = _make_note(cleaned["title"], cleaned.get("body", ""))
        response = JsonResponse(note, status_code=201)
        response.headers["Location"] = f"/api/notes/{note['id']}/"
        return response


# ---------------------------------------------------------------------------
# UUID path converter
# ---------------------------------------------------------------------------


class EchoUUIDAPIView(APIView):
    """Echoes a UUID path parameter so the `<uuid:>` converter shows up in the spec."""

    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "Echoed UUID.",
                    "content": openapi.json_content(
                        {
                            "type": "object",
                            "required": ["id"],
                            "properties": {"id": {"type": "string", "format": "uuid"}},
                        }
                    ),
                }
            }
        }
    )
    def get(self):
        echoed: uuid.UUID = self.url_kwargs["id"]
        return {"id": str(echoed)}


# ---------------------------------------------------------------------------
# Required header parameter
# ---------------------------------------------------------------------------


class HeaderEchoAPIView(APIView):
    """Requires a custom `X-Demo-Header` and echoes its value."""

    @openapi.schema(
        {
            "parameters": [
                {
                    "name": "X-Demo-Header",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Required custom header.",
                }
            ],
            "responses": {
                "200": {
                    "description": "Echoed header.",
                    "content": openapi.json_content(
                        {
                            "type": "object",
                            "required": ["value"],
                            "properties": {"value": {"type": "string"}},
                        }
                    ),
                },
            },
        }
    )
    def get(self):
        value = self.request.headers.get("X-Demo-Header")
        if not value:
            raise BadRequestError400("Missing X-Demo-Header")
        return {"value": value}


# ---------------------------------------------------------------------------
# API key auth (security scheme + per-operation `security` auto-emitted)
# ---------------------------------------------------------------------------


class SecretAPIView(APIView, ConformanceAPIKeyView):
    """Requires `Authorization: Bearer conformance-key`."""

    @openapi.schema(
        {
            "responses": {
                "200": {
                    "description": "Authenticated.",
                    "content": openapi.json_content(
                        {
                            "type": "object",
                            "required": ["ok"],
                            "properties": {"ok": {"type": "boolean"}},
                        }
                    ),
                },
            },
        }
    )
    def get(self):
        return {"ok": True}


# ---------------------------------------------------------------------------
# API versioning
# ---------------------------------------------------------------------------


class ChangeToName(APIVersionChange):
    description = "'to' renamed to 'name' on the request"

    def transform_request_forward(self, request, data):
        if "to" in data:
            data["name"] = data.pop("to")


class ChangeMsgMessage(APIVersionChange):
    description = "'message' renamed to 'msg' on the response (v1)"

    def transform_response_backward(self, response, data):
        if "message" in data:
            data["msg"] = data.pop("message")


class GreetingAPIView(VersionedAPIView):
    api_versions = {
        "v2": [],
        "v1": [ChangeToName, ChangeMsgMessage],
    }
    default_api_version = "v2"

    @openapi.schema(
        {
            "parameters": [
                {
                    "name": "API-Version",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "enum": ["v1", "v2"]},
                    "description": "API version to dispatch on.",
                }
            ],
            "requestBody": openapi.json_body(
                {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                }
            ),
            "responses": {
                "200": {
                    "description": "Greeting.",
                    "content": openapi.json_content(
                        {
                            "type": "object",
                            "required": ["message"],
                            "properties": {"message": {"type": "string"}},
                        }
                    ),
                },
            },
        }
    )
    def post(self):
        data = self.request.json_data
        if not isinstance(data, dict) or "name" not in data:
            raise BadRequestError400("Missing `name`")
        name = data["name"]
        if not isinstance(name, str):
            raise BadRequestError400("Invalid `name`")
        return {"message": f"Hello, {name}!"}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@openapi.schema(
    {
        "openapi": "3.0.3",
        "info": {
            "title": "Plain API Conformance Fixture",
            "version": "1.0.0",
            "description": (
                "Minimal API surface used to verify that the OpenAPI spec "
                "produced by `plain api generate-openapi` matches the runtime "
                "behavior of `plain server`."
            ),
        },
    }
)
class APIRouter(Router):
    namespace = "api"
    openapi_components = {
        "schemas": {
            "Note": {
                "type": "object",
                "required": ["id", "title", "body"],
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
            "NoteInput": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                    "body": {"type": "string"},
                },
            },
            "NotePatch": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                    "body": {"type": "string"},
                },
            },
        },
        "parameters": {
            "Limit": {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 25,
                },
                "description": "Maximum number of items to return.",
            }
        },
    }
    urls = [
        path("notes/", NoteListAPIView, name="notes_list"),
        path("notes/<int:id>/", NoteDetailAPIView, name="notes_detail"),
        path("echo-uuid/<uuid:id>/", EchoUUIDAPIView, name="echo_uuid"),
        path("header-echo/", HeaderEchoAPIView, name="header_echo"),
        path("secret/", SecretAPIView, name="secret"),
        path("greeting/", GreetingAPIView, name="greeting"),
        path("<path:_>", JsonNotFoundView, name="not_found"),
    ]
