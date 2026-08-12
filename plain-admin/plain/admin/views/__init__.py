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
from .types import Avatar, Img
from .viewsets import AdminViewset

__all__ = [
    "AdminCreateView",
    "AdminDeleteView",
    "AdminDetailView",
    "AdminListView",
    "AdminModelCreateView",
    "AdminModelDeleteView",
    "AdminModelDetailView",
    "AdminModelListView",
    "AdminModelUpdateView",
    "AdminUpdateView",
    "AdminView",
    "AdminViewset",
    "Avatar",
    "Img",
    "get_model_detail_url",
    "register_view",
    "register_viewset",
]
