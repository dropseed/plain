from plain.urls import path
from plain.views import View


class TestView(View):
    def get(self):
        return "Hello, world!"


urlpatterns = [
    path("", TestView),
]
