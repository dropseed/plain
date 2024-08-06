# The views used below are normally mapped in the StaffSite instance.
# This URLs file is used to provide a reliable view deployment for test purposes.
# It is also provided as a convenience to those who want to deploy these URLs
# elsewhere.

from plain.urls import path

from . import views

urlpatterns = [
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
