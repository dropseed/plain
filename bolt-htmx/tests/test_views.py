from django.http import HttpResponse
from django.views import View

from forgehtmx.views import HTMXViewMixin


class V(HTMXViewMixin, View):
    def get(self, request):
        return HttpResponse("Ok")


def test_is_htmx_request(rf):
    request = rf.get("/", HTTP_HX_REQUEST="true")
    view = V()
    view.setup(request)
    assert view.is_htmx_request


def test_fhx_fragment(rf):
    request = rf.get("/", HTTP_FHX_FRAGMENT="main")
    view = V()
    view.setup(request)
    assert view.htmx_fragment_name == "main"


def test_fhx_action(rf):
    request = rf.get("/", HTTP_FHX_ACTION="create")
    view = V()
    view.setup(request)
    assert view.htmx_action_name == "create"
