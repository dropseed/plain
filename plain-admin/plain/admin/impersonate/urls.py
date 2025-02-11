from plain.urls import path

from .views import ImpersonateStartView, ImpersonateStopView

default_namespace = "impersonate"

urlpatterns = [
    path("stop/", ImpersonateStopView, name="stop"),
    path("start/<pk>/", ImpersonateStartView, name="start"),
]
