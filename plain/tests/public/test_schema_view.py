"""SchemaView contract: GET renders an unbound form, POST validates and
either re-renders with errors or calls schema_valid()."""

from __future__ import annotations

from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.http import Response
from plain.schema import BoundSchema, Schema, types
from plain.views import SchemaView


class _NoteSchema(Schema):
    title: str = types.TextField(min_length=2)
    body: str = types.TextField(required=False, initial="")


class _NoteView(SchemaView[_NoteSchema]):
    schema_class = _NoteSchema
    template_name = "ignored"
    success_url = "/done"

    # Override the rendering paths so we don't need a real template.
    schema_valid_calls: list[_NoteSchema] = []
    schema_invalid_calls: list[BoundSchema] = []

    def schema_valid(self, result: _NoteSchema) -> Response:
        self.schema_valid_calls.append(result)
        return Response(status_code=204)

    def schema_invalid(self, bound: BoundSchema) -> Response:
        self.schema_invalid_calls.append(bound)
        return Response(status_code=422)


class _FakeRequest:
    """Just enough surface for SchemaView.post() — avoids spinning up a
    full Plain test app for unit-level coverage."""

    method = "POST"

    def __init__(self, form_data: dict, files: dict | None = None) -> None:
        self.form_data = form_data
        self.files = files or {}


def _make_view(form_data: dict | None = None, files: dict | None = None) -> _NoteView:
    request = _FakeRequest(form_data or {}, files)
    view = _NoteView(request=request)  # ty: ignore[invalid-argument-type]
    view.schema_valid_calls = []
    view.schema_invalid_calls = []
    return view


def test_post_with_valid_data_calls_schema_valid():
    view = _make_view({"title": "Q3", "body": "report"})
    response = view.post()
    assert response.status_code == 204
    assert len(view.schema_valid_calls) == 1
    assert view.schema_valid_calls[0].title == "Q3"
    assert len(view.schema_invalid_calls) == 0


def test_post_with_invalid_data_calls_schema_invalid_with_bound():
    view = _make_view({"title": "X"})  # min_length=2 violated
    response = view.post()
    assert response.status_code == 422
    assert len(view.schema_invalid_calls) == 1

    bound = view.schema_invalid_calls[0]
    assert bound.is_bound
    assert bound.errors.get("title")
    assert bound.title.value() == "X"  # raw value preserved for re-display


def test_get_template_context_includes_unbound_bound_schema():
    view = _make_view({})
    view.request.method = "GET"  # ty: ignore[invalid-assignment]
    context = view.get_template_context()
    bound = context["form"]
    assert isinstance(bound, BoundSchema)
    assert not bound.is_bound  # unbound on GET
    assert bound.title.value() is None


def test_missing_schema_class_raises_improperlyconfigured():
    class _Bad(SchemaView):
        template_name = "ignored"

    view = _Bad(request=_FakeRequest({}))  # ty: ignore[invalid-argument-type]

    import pytest

    with pytest.raises(ImproperlyConfigured, match="schema_class"):
        view.post()


def test_default_schema_valid_redirects_to_success_url():
    """Without a schema_valid override, a successful POST redirects."""

    class _DefaultView(SchemaView[_NoteSchema]):
        schema_class = _NoteSchema
        template_name = "ignored"
        success_url = "/thanks"

    view = _DefaultView(
        request=_FakeRequest({"title": "ok"})  # ty: ignore[invalid-argument-type]
    )
    response = view.post()
    assert response.status_code == 302
    assert response.headers["Location"] == "/thanks"


def test_initial_passed_to_bound_schema_on_invalid():
    class _InitialView(_NoteView):
        def get_initial(self) -> dict[str, Any]:
            return {"title": "default"}

    view = _InitialView(
        request=_FakeRequest({"title": ""})  # ty: ignore[invalid-argument-type]
    )
    view.schema_invalid_calls = []
    view.post()

    assert len(view.schema_invalid_calls) == 1
    bound = view.schema_invalid_calls[0]
    # The user submitted blank, raw wins for display
    assert bound.title.value() == ""
    # initial preserved on the bound form
    assert bound.initial == {"title": "default"}
