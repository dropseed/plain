import plain.admin.urls
import plain.assets.urls
from plain.urls import RouterBase, include, path, register_router
from plain.views import View


class LoginView(View):
    def get(self):
        return "Login!"


class LogoutView(View):
    def get(self):
        return "Logout!"


@register_router
class Router(RouterBase):
    urls = [
        include("admin/", plain.admin.urls),
        include("assets/", plain.assets.urls),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
    ]
