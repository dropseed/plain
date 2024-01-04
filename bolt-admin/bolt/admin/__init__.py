from .views.base import (
    AdminDeleteView,
    AdminDetailView,
    AdminListView,
    AdminPageView,
    AdminUpdateView,
)
from .views.models import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelUpdateView,
    AdminModelViewset,
)
from .views.registry import (
    register_dashboard,
    register_view,
    register_viewset,
)

__all__ = [
    "AdminPageView",
    "AdminListView",
    "AdminDetailView",
    "AdminUpdateView",
    "AdminDeleteView",
    "AdminModelViewset",
    "AdminModelListView",
    "AdminModelDetailView",
    "AdminModelUpdateView",
    "register_viewset",
    "register_view",
    "register_dashboard",
]
