from plain.htmx.views import HTMXViewMixin
from plain.http import Response
from plain.views import View


class V(HTMXViewMixin, View):
    def get(self, request):
        return Response("Ok")


def test_is_htmx_request(rf):
    request = rf.get("/", HTTP_HX_REQUEST="true")
    view = V()
    view.setup(request)
    assert view.is_htmx_request()


def test_bhx_fragment(rf):
    request = rf.get("/", HTTP_BHX_FRAGMENT="main")
    view = V()
    view.setup(request)
    assert view.get_htmx_fragment_name() == "main"


def test_bhx_action(rf):
    request = rf.get("/", HTTP_BHX_ACTION="create")
    view = V()
    view.setup(request)
    assert view.get_htmx_action_name() == "create"
