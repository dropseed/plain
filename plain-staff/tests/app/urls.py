import plain.staff.urls
from plain.urls import include, path
from plain.views import View


class LoginView(View):
    def get(self):
        return "Login!"


class LogoutView(View):
    def get(self):
        return "Logout!"


urlpatterns = [
    path("staff/", include(plain.staff.urls)),
    path("login/", LoginView, name="login"),
    path("logout/", LogoutView, name="logout"),
]
