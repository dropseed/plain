from plain.htmx.views import HTMXView
from plain.http import Response
from plain.test import RequestFactory


class V(HTMXView):
    def get(self):
        return Response("Ok")


def test_is_htmx_request():
    request = RequestFactory().get("/", headers={"HX-Request": "true"})
    view = V()
    view.setup(request)
    assert view.is_htmx_request()


def test_plain_hx_fragment():
    request = RequestFactory().get("/", headers={"Plain-HX-Fragment": "main"})
    view = V()
    view.setup(request)
    assert view.get_htmx_fragment_name() == "main"


def test_plain_hx_action():
    request = RequestFactory().get("/", headers={"Plain-HX-Action": "create"})
    view = V()
    view.setup(request)
    assert view.get_htmx_action_name() == "create"
