from typing import Any

from .base import Card


class KeyValueCard(Card):
    template_name = "admin/cards/key_value.html"

    items: dict[str, Any] = {}

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["items"] = self.get_items()
        return context

    def get_items(self) -> dict[str, Any]:
        return self.items.copy()
