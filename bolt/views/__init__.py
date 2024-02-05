from .base import View
from .forms import FormView
from .objects import CreateView, DeleteView, DetailView, ListView, UpdateView
from .redirect import RedirectView
from .templates import TemplateView

__all__ = [
    "View",
    "TemplateView",
    "RedirectView",
    "FormView",
    "DetailView",
    "CreateView",
    "UpdateView",
    "DeleteView",
    "ListView",
    "AuthViewMixin",
]
