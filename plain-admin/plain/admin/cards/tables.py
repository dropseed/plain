from typing import Any

from .base import Card


class TableCard(Card):
    template_name = "admin/cards/table.html"
    size = Card.Sizes.FULL

    headers = []
    rows = []
    footers = []

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["headers"] = self.get_headers()
        context["rows"] = self.get_rows()
        context["footers"] = self.get_footers()
        return context

    def get_headers(self) -> list:
        return self.headers.copy()

    def get_rows(self) -> list:
        return self.rows.copy()

    def get_footers(self) -> list:
        return self.footers.copy()
