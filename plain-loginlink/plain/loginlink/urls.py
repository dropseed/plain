from plain.urls import path

from . import views

default_namespace = "loginlink"


urlpatterns = [
    path("sent/", views.LoginLinkSentView.as_view(), name="sent"),
    path("failed/", views.LoginLinkFailedView.as_view(), name="failed"),
    path("token/<str:token>/", views.LoginLinkLoginView.as_view(), name="login"),
]
