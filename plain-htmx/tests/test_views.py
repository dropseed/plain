from plain.htmx.views import HTMXViewMixin
from plain.http import Response
from plain.test import RequestFactory
from plain.views import View


class V(HTMXViewMixin, View):
    def get(self):
        return Response("Ok")


def test_is_htmx_request():
    request = RequestFactory().get("/", HTTP_HX_REQUEST="true")
    view = V()
    view.setup(request)
    assert view.is_htmx_request()


def test_plain_hx_fragment():
    request = RequestFactory().get("/", HTTP_PLAIN_HX_FRAGMENT="main")
    view = V()
    view.setup(request)
    assert view.get_htmx_fragment_name() == "main"


def test_plain_hx_action():
    request = RequestFactory().get("/", HTTP_PLAIN_HX_ACTION="create")
    view = V()
    view.setup(request)
    assert view.get_htmx_action_name() == "create"
