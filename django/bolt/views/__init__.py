from .auth import AuthViewMixin
from .base import View
from .forms import FormView
from .objects import CreateView, DeleteView, DetailView, UpdateView

# from .list import ListView
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
    # "ListView",
    "AuthViewMixin",
]
