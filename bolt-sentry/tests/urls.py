from django.urls import path
from django.views.generic import TemplateView


class ErrorView(TemplateView):
    template_name = "index.html"  # Won't actually render this, will error instead

    def get_context_data(self, **kwargs):
        raise Exception("Test!")


urlpatterns = [
    path("error/", ErrorView.as_view()),
    path("", TemplateView.as_view(template_name="index.html"), name="index"),
]
