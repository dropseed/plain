from .base import AdminView
from .models import (
    AdminModelCreateView,
    AdminModelDeleteView,
    AdminModelDetailView,
    AdminModelListView,
    AdminModelUpdateView,
)
from .objects import (
    AdminCreateView,
    AdminDeleteView,
    AdminDetailView,
    AdminListView,
    AdminUpdateView,
)
from .registry import (
    get_model_detail_url,
    register_view,
    register_viewset,
)
from .types import Img
from .viewsets import AdminViewset

__all__ = [
    "AdminView",
    "AdminListView",
    "AdminCreateView",
    "AdminUpdateView",
    "AdminDetailView",
    "AdminDeleteView",
    "AdminViewset",
    "AdminModelListView",
    "AdminModelCreateView",
    "AdminModelDetailView",
    "AdminModelUpdateView",
    "AdminModelDeleteView",
    "register_viewset",
    "register_view",
    "get_model_detail_url",
    "Img",
]
