from django.urls import path

from .views import ImpersonateStartView, ImpersonateStopView

app_name = "impersonate"

urlpatterns = [
    path("stop/", ImpersonateStopView.as_view(), name="stop"),
    path("start/<pk>/", ImpersonateStartView.as_view(), name="start"),
]
