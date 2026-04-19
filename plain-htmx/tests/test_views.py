from plain.htmx.views import HTMXView
from plain.http import Response
from plain.test import RequestFactory


class V(HTMXView):
    def get(self):
        return Response("Ok")


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
