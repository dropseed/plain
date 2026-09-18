from typing import Any

from .base import Card


class TableCard(Card):
    template_name = "admin/cards/table.html"
    size = Card.Sizes.FULL

    headers: tuple = ()
    rows: tuple = ()
    footers: tuple = ()

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["headers"] = self.get_headers()
        context["rows"] = self.get_rows()
        context["footers"] = self.get_footers()
        return context

    def get_headers(self) -> tuple:
        return self.headers

    def get_rows(self) -> tuple:
        return self.rows

    def get_footers(self) -> tuple:
        return self.footers
