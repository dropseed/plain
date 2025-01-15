from .base import (
    StaffDeleteView,
    StaffDetailView,
    StaffListView,
    StaffUpdateView,
    StaffView,
)
from .models import (
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
    "StaffDetailView",
    "StaffUpdateView",
    "StaffDeleteView",
    "StaffModelViewset",
    "StaffModelListView",
    "StaffModelDetailView",
    "StaffModelUpdateView",
    "register_viewset",
    "register_view",
    "get_model_detail_url",
    "Img",
]
