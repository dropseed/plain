from .views.base import AdminListView, AdminPageView
from .views.cards import (
    AdminCardView,
    AdminChartCardView,
    AdminStatCardView,
    AdminTextCardView,
    AdminTrendCardView,
)
from .views.models import AdminModelViewset
from .views.registry import (
    register_card,
    register_dashboard,
    register_model,
    register_view,
)

__all__ = [
    "AdminPageView",
    "AdminListView",
    "AdminModelViewset",
    "AdminCardView",
    "AdminTextCardView",
    "AdminChartCardView",
    "AdminTrendCardView",
    "AdminStatCardView",
    "register_model",
    "register_card",
    "register_view",
    "register_dashboard",
]
