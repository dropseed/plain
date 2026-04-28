import pytest

from plain.htmx.views import HTMXView
from plain.http import Response
from plain.test import RequestFactory


class V(HTMXView):
    def get(self):
        return Response("Ok")


class ActionView(HTMXView):
    """HTMXView with stubbed render_template so the dispatch path can be exercised
    end-to-end without setting up a real template environment."""

    rendered_body = "<p>rendered</p>"

    def render_template(self) -> str:
        return self.rendered_body

    def htmx_post_save(self) -> None:
        # Explicit None — should trigger a re-render of the current template.
        return None

    def htmx_post_implicit(self) -> None:
        # No return statement at all — the dominant ergonomic case.
        pass

    def htmx_post_redirect(self) -> Response:
        return Response("redirected", status_code=204)

    def htmx_post_bad_return(self) -> str:  # ty: ignore[invalid-return-type]
        # Wrong return type — must raise loudly, not silently propagate.
        return "not a response"


class FragmentActionView(HTMXView):
    """Surfaces the request state observed by render_template so the fragment
    header can be verified end-to-end."""

    def render_template(self) -> str:
        return f"htmx={self.is_htmx_request()};fragment={self.get_htmx_fragment_name()}"

    def htmx_post_save(self) -> None:
        return None


def test_is_htmx_request():
    request = RequestFactory().get("/", headers={"HX-Request": "true"})
    view = V(request=request)
    assert view.is_htmx_request()


def test_plain_hx_fragment():
    request = RequestFactory().get("/", headers={"Plain-HX-Fragment": "main"})
    view = V(request=request)
    assert view.get_htmx_fragment_name() == "main"


def test_plain_hx_action():
    request = RequestFactory().get("/", headers={"Plain-HX-Action": "create"})
    view = V(request=request)
    assert view.get_htmx_action_name() == "create"


def test_unknown_action_returns_no_handler():
    """Unknown action headers must not raise AttributeError.

    Previously `getattr(self, f"{method}_{action}")` had no default, so
    any client-supplied action that didn't match a method produced a 500.
    """
    request = RequestFactory().post(
        "/", headers={"HX-Request": "true", "Plain-HX-Action": "does_not_exist"}
    )
    view = V(request=request)
    assert view.get_request_handler() is None


def test_non_identifier_action_returns_no_handler():
    """Action strings containing dots, dashes, etc. must not be looked up."""
    request = RequestFactory().post(
        "/", headers={"HX-Request": "true", "Plain-HX-Action": "foo.bar"}
    )
    view = V(request=request)
    assert view.get_request_handler() is None


def test_non_standard_method_does_not_dispatch():
    """Non-IANA HTTP methods must not be used to invoke view attributes."""
    request = RequestFactory().generic(
        "GET_RESPONSE", "/", headers={"HX-Request": "true"}
    )
    view = V(request=request)
    assert view.get_request_handler() is None


def test_action_returning_none_rerenders_template():
    """Action handlers may return None to mean 're-render the template/fragment'."""
    request = RequestFactory().post(
        "/", headers={"HX-Request": "true", "Plain-HX-Action": "save"}
    )
    view = ActionView(request=request)
    response = view.get_response()
    assert response.status_code == 200
    assert response.content.decode() == ActionView.rendered_body


def test_action_returning_response_passes_through():
    """An explicit Response from an action handler is used as-is."""
    request = RequestFactory().post(
        "/", headers={"HX-Request": "true", "Plain-HX-Action": "redirect"}
    )
    view = ActionView(request=request)
    response = view.get_response()
    assert response.status_code == 204
    assert response.content.decode() == "redirected"


def test_convert_result_to_response_none_renders_template():
    """convert_result_to_response wraps None by calling render_template."""
    request = RequestFactory().post("/", headers={"HX-Request": "true"})
    view = ActionView(request=request)
    response = view.convert_result_to_response(None)
    assert isinstance(response, Response)
    assert response.content.decode() == ActionView.rendered_body


def test_convert_result_to_response_passes_response_through():
    request = RequestFactory().post("/", headers={"HX-Request": "true"})
    view = ActionView(request=request)
    original = Response("custom", status_code=418)
    response = view.convert_result_to_response(original)
    assert response is original


def test_action_with_implicit_return_rerenders():
    """Falling off the end of an action handler (no `return`) re-renders.

    This is the dominant ergonomic case — the framework's pitch is that you
    can write a handler that just mutates state and let the framework re-render.
    """
    request = RequestFactory().post(
        "/", headers={"HX-Request": "true", "Plain-HX-Action": "implicit"}
    )
    view = ActionView(request=request)
    response = view.get_response()
    assert response.status_code == 200
    assert response.content.decode() == ActionView.rendered_body


def test_rerender_observes_fragment_header():
    """When re-rendering on None, render_template sees the active fragment header
    so fragment-aware rendering still kicks in."""
    request = RequestFactory().post(
        "/",
        headers={
            "HX-Request": "true",
            "Plain-HX-Action": "save",
            "Plain-HX-Fragment": "main",
        },
    )
    view = FragmentActionView(request=request)
    response = view.get_response()
    assert response.content.decode() == "htmx=True;fragment=main"


def test_invalid_return_type_raises():
    """Returning something that isn't None or Response must fail loudly."""
    request = RequestFactory().post(
        "/", headers={"HX-Request": "true", "Plain-HX-Action": "bad_return"}
    )
    view = ActionView(request=request)
    with pytest.raises(TypeError, match="must return a Response or None"):
        view.get_response()
