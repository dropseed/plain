from plain.urls import path
from plain.views import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="index"),
]
