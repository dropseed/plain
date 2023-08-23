from django.views.generic import TemplateView

from bolt.urls import path

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="index"),
]
