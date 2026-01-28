from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from plain.http import Request
from plain.templates import Template

if TYPE_CHECKING:
    from plain.admin.views import AdminView


class Card:
    class Sizes(Enum):
        # Four column grid
        SMALL = 1
        MEDIUM = 2
        LARGE = 3
        FULL = 4

    template_name = "admin/cards/card.html"
    size: Sizes = Sizes.SMALL
    # unique_id: str  # Use for tying to dashboards, require it

    # Required fields
    title: str

    # Optional fields
    description: str = ""
    text: str = ""
    link: str = ""
    metric: int | float | Decimal | None = None
    filters: list[str] | Enum | None = None

    # These will be accessible at render time
    view: AdminView
    request: Request

    def render(self, view: AdminView, request: Request) -> str:
        self.view = view
        self.request = request
        return Template(self.template_name).render(self.get_template_context())

    @classmethod
    def view_name(cls) -> str:
        return f"card_{cls.get_slug()}"

    def get_template_context(self) -> dict[str, Any]:
        context = {}

        context["request"] = self.request
        context["size"] = self.size
        context["title"] = self.get_title()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["metric"] = self.format_metric()
        context["text"] = self.get_text()
        context["link"] = self.get_link()
        context["filters"] = self.get_filters()
        context["current_filter"] = self.get_current_filter()

        return context

    def get_title(self) -> str:
        return self.title

    @classmethod
    def get_slug(cls) -> str:
        return f"{cls.__module__}.{cls.__name__}".lower().replace(".", "_")

    def get_description(self) -> str:
        return self.description

    def get_metric(self) -> int | float | Decimal | None:
        return self.metric

    def format_metric(self) -> str | None:
        metric = self.get_metric()
        if metric is None:
            return None
        return str(metric)

    def get_text(self) -> str:
        return self.text

    def get_link(self) -> str:
        return self.link

    def get_current_filter(self) -> str:
        return self.request.query_params.get(f"{self.get_slug()}.filter", "")

    def get_filters(self) -> list[str] | Enum | None:
        if isinstance(self.filters, list):
            # Avoid mutating the class attribute
            return self.filters.copy()  # type: ignore
        else:
            return self.filters
