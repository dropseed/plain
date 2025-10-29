from enum import Enum
from typing import Any

from plain.http import Request
from plain.templates import Template
from plain.views import View


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
    number: int | None = None
    presets: list[str] | Enum | None = None

    # These will be accessible at render time
    view: View
    request: Request

    def render(self, view: View, request: Request) -> str:
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
        context["number"] = self.get_number()
        context["text"] = self.get_text()
        context["link"] = self.get_link()
        context["presets"] = self.get_presets()
        context["current_preset"] = self.get_current_preset()

        return context

    def get_title(self) -> str:
        return self.title

    @classmethod
    def get_slug(cls) -> str:
        return f"{cls.__module__}.{cls.__name__}".lower().replace(".", "_")

    def get_description(self) -> str:
        return self.description

    def get_number(self) -> int | None:
        return self.number

    def get_text(self) -> str:
        return self.text

    def get_link(self) -> str:
        return self.link

    def get_current_preset(self) -> str:
        return self.request.query_params.get(f"{self.get_slug()}.preset", "")

    def get_presets(self) -> list[str] | Enum | None:
        if hasattr(self.presets, "copy"):
            # Avoid mutating the class attribute
            return self.presets.copy()
        else:
            return self.presets
