from enum import Enum

from .base import BaseAdminView


class AdminPanelView(BaseAdminView):
    class PanelSize(Enum):
        # Three column grid
        SM = 1
        MD = 2
        LG = 3
        XL = 3

    template_name = "bolt/admin/panel.html"
    size: PanelSize = PanelSize.MD

    def get_context(self) -> dict:
        context = super().get_context()
        context["panel_slug"] = self.slug
        return context

    @classmethod
    def view_name(cls) -> str:
        return f"panel_{cls.slug}"


class AdminTextPanelView(AdminPanelView):
    text: str = ""
    template_name = "bolt/admin/panels/text.html"

    def get_context(self):
        context = super().get_context()
        context["text"] = self.get_text()
        return context

    def get_text(self) -> str:
        return self.text


class AdminChartPanelView(AdminPanelView):
    template_name = "bolt/admin/panels/chart.html"

    def get_context(self):
        context = super().get_context()
        context["chart_data"] = self.get_chart_data()
        return context

    def get_chart_data(self) -> dict:
        raise NotImplementedError
