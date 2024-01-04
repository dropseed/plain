from enum import Enum

from bolt import jinja
from bolt.utils.text import slugify


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
    slug: str = ""
    description: str = ""
    text: str = ""
    link: str = ""
    number: int | None = None

    def render(self, request):
        template = jinja.environment.get_template(self.template_name)
        return template.render(self.get_context())

    @classmethod
    def view_name(cls) -> str:
        return f"card_{cls.get_slug()}"

    def get_context(self):
        context = {}
        context["title"] = self.get_title()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["number"] = self.get_number()
        context["text"] = self.get_text()
        context["link"] = self.get_link()
        return context

    def get_title(self) -> str:
        return self.title

    def get_slug(self) -> str:
        return self.slug or slugify(self.title)

    def get_description(self) -> str:
        return self.description

    def get_number(self) -> int | None:
        return self.number

    def get_text(self) -> str:
        return self.text

    def get_link(self) -> str:
        return self.link
