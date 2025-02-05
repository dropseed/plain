from .base import (
    StaffCreateView,
    StaffDeleteView,
    StaffDetailView,
    StaffListView,
    StaffUpdateView,
    StaffView,
)
from .models import (
    StaffModelCreateView,
    StaffModelDeleteView,
    StaffModelDetailView,
    StaffModelListView,
    StaffModelUpdateView,
    StaffModelViewset,
)
from .registry import (
    get_model_detail_url,
    register_view,
    register_viewset,
)
from .types import Img

__all__ = [
    "StaffView",
    "StaffListView",
    "StaffCreateView",
    "StaffUpdateView",
    "StaffDetailView",
    "StaffDeleteView",
    "StaffModelViewset",
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
