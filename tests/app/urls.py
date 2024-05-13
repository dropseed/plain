from bolt.urls import path
from bolt.views import View


class TestView(View):
    def get(self):
        return "Hello, world!"


urlpatterns = [
    path("", TestView),
]
