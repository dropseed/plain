from plain.urls import RouterBase, path, register_router
from plain.views import View


class IndexView(View):
    def get(self):
        # Store something so the session is saved
        self.request.session["foo"] = "bar"
        return "test"


@register_router
class Router(RouterBase):
    urls = [
        path("", IndexView),
    ]
