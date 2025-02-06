from .base import StaffView
from .models import (
    StaffModelCreateView,
    StaffModelDeleteView,
    StaffModelDetailView,
    StaffModelListView,
    StaffModelUpdateView,
)
from .objects import (
    StaffCreateView,
    StaffDeleteView,
    StaffDetailView,
    StaffListView,
    StaffUpdateView,
)
from .registry import (
    get_model_detail_url,
    register_view,
    register_viewset,
)
from .types import Img
from .viewsets import StaffViewset

__all__ = [
    "StaffView",
    "StaffListView",
    "StaffCreateView",
    "StaffUpdateView",
    "StaffDetailView",
    "StaffDeleteView",
    "StaffViewset",
    "StaffModelListView",
    "StaffModelCreateView",
    "StaffModelDetailView",
    "StaffModelUpdateView",
    "StaffModelDeleteView",
    "register_viewset",
    "register_view",
    "get_model_detail_url",
    "Img",
]
