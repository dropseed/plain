from __future__ import annotations

from plain.test import Client
from plain.views import View


class _FakeRequest:
    def __init__(self, method: str) -> None:
        self.method = method


def _dispatch(view_class: type[View], method: str):
    view = view_class(request=_FakeRequest(method))  # ty: ignore[invalid-argument-type]
    handler = view.get_request_handler()
    return handler() if handler else None


def test_unknown_method_is_not_allowed():
    """Non-standard HTTP methods must not invoke arbitrary view attributes.

    Previously `getattr(self, method.lower())` with no whitelist meant a
    request with method `GET_RESPONSE` would recursively call
    `View.get_response`, blowing the stack.
    """
    client = Client()

    for method in ("GET_RESPONSE", "GET_REQUEST_HANDLER", "_ALLOWED_METHODS"):
        request = client._request_factory.generic(method, "/")
        response = client.request(request)
        assert response.status_code == 405, (
            f"method={method} returned {response.status_code}"
        )


def test_standard_methods_still_dispatch():
    client = Client()
    assert client.get("/").status_code == 200


def test_head_falls_back_to_get():
    """A view defining only `get` should also handle HEAD (over the wire)."""
    client = Client()
    assert client.head("/").status_code == 200


def test_head_dispatches_to_subclass_get_override():
    """HEAD on a subclass that overrides `get` must call the subclass's `get`."""

    class Parent(View):
        def get(self):
            return "parent"

    class Child(Parent):
        def get(self):
            return "child"

    assert _dispatch(Child, "HEAD") == "child"


def test_explicit_head_wins_over_get_fallback():
    """A view that defines both `head` and `get` uses `head` for HEAD."""

    class MyView(View):
        def get(self):
            return "get-body"

        def head(self):
            return "head-body"

    assert _dispatch(MyView, "HEAD") == "head-body"


def test_inherited_explicit_head_wins_over_subclass_get():
    """If an ancestor defines `head`, a subclass adding `get` does not override it."""

    class OnlyHead(View):
        def head(self):
            return "only-head"

    class SubWithGet(OnlyHead):
        def get(self):
            return "sub-get"

    assert _dispatch(SubWithGet, "HEAD") == "only-head"


def test_allowed_methods_includes_head_when_get_defined():
    """`_allowed_methods` should advertise HEAD when GET is available."""

    class MyView(View):
        def get(self):
            return "x"

    view = MyView(request=_FakeRequest("GET"))  # ty: ignore[invalid-argument-type]
    assert "HEAD" in view._allowed_methods()


def test_implemented_methods_tracks_overrides():
    """`implemented_methods` should reflect exactly the handlers a subclass provides."""

    class GetOnly(View):
        def get(self):
            return "x"

    class GetAndPost(View):
        def get(self):
            return "x"

        def post(self):
            return "y"

    assert GetOnly.implemented_methods == frozenset({"get"})
    assert GetAndPost.implemented_methods == frozenset({"get", "post"})
    assert View.implemented_methods == frozenset()


def test_implemented_methods_picks_up_mixins():
    """Handlers defined on mixins should count as implemented on the composed class."""

    class PostMixin:
        def post(self):
            return "m"

    class Composed(PostMixin, View):
        def get(self):
            return "g"

    assert Composed.implemented_methods == frozenset({"get", "post"})


def test_options_always_responds():
    """OPTIONS should always dispatch to the base handler and return an Allow header."""
    client = Client()
    response = client.options("/")
    assert response.status_code == 200
    assert "OPTIONS" in response.headers.get("Allow", "")


def test_undefined_method_returns_405():
    """A view defining only `get` should 405 on POST."""

    class GetOnly(View):
        def get(self):
            return "x"

    view = GetOnly(request=_FakeRequest("POST"))  # ty: ignore[invalid-argument-type]
    assert view.get_request_handler() is None


def test_trace_and_connect_are_not_dispatched():
    """TRACE and CONNECT are intentionally excluded from view handlers."""

    class MyView(View):
        def get(self):
            return "x"

    assert _dispatch(MyView, "TRACE") is None
    assert _dispatch(MyView, "CONNECT") is None
