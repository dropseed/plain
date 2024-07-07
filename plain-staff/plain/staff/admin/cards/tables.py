from .base import Card


class TableCard(Card):
    template_name = "admin/cards/table.html"
    size = Card.Sizes.FULL

    headers = []
    rows = []
    footers = []

    def get_template_context(self):
        context = super().get_template_context()
        context["headers"] = self.get_headers()
        context["rows"] = self.get_rows()
        context["footers"] = self.get_footers()
        return context

    def get_headers(self):
        return self.headers.copy()

    def get_rows(self):
        return self.rows.copy()

    def get_footers(self):
        return self.footers.copy()
