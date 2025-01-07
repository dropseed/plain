from plain.urls import path

from . import views

default_namespace = "support"


urlpatterns = [
    path("form/<slug:form_slug>.js", views.SupportFormJSView),
    path("form/<slug:form_slug>/iframe/", views.SupportIFrameView, name="iframe"),
    path("form/<slug:form_slug>/", views.SupportFormView, name="form"),
]
