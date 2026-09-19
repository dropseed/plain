from app.examples import views
from plain.urls import Router, path
from plain.views import View


class LoginView(View):
    def get(self):
        return "Login!"


class LogoutView(View):
    def get(self):
        return "Logout!"


class AppRouter(Router):
    namespace = ""
    urls = (
        path("login", LoginView, name="login"),
        path("logout", LogoutView, name="logout"),
        path("widgets/new", views.WidgetCreateView, name="widget_create"),
        path("widgets/<int:id>/edit", views.WidgetUpdateView, name="widget_update"),
        path("widgets/<int:id>/delete", views.WidgetDeleteView, name="widget_delete"),
    )
