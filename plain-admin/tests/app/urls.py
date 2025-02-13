import plain.admin.urls
import plain.assets.urls
from plain.urls import include, path
from plain.views import View


class LoginView(View):
    def get(self):
        return "Login!"


class LogoutView(View):
    def get(self):
        return "Logout!"


urlpatterns = [
    path("admin/", include(plain.admin.urls)),
    path("assets/", include(plain.assets.urls)),
    path("login/", LoginView, name="login"),
    path("logout/", LogoutView, name="logout"),
]
