from plain.urls import RouterBase, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "passwords"
    urls = [
        path("password_change/", views.PasswordChangeView, name="password_change"),
        path(
            "password_change/done/",
            views.PasswordChangeDoneView,
            name="password_change_done",
        ),
        path("password_reset/", views.PasswordResetView, name="password_reset"),
        path(
            "password_reset/done/",
            views.PasswordResetDoneView,
            name="password_reset_done",
        ),
        path(
            "reset/<uidb64>/<token>/",
            views.PasswordResetConfirmView,
            name="password_reset_confirm",
        ),
        path(
            "reset/done/",
            views.PasswordResetCompleteView,
            name="password_reset_complete",
        ),
    ]
