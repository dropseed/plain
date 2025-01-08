from enum import Enum

from plain.http import HttpRequest
from plain.staff.dates import DatetimeRange, DatetimeRangeAliases
from plain.templates import Template
from plain.utils.text import slugify
from plain.views import View


class Card:
    class Sizes(Enum):
        # Four column grid
        SMALL = 1
        MEDIUM = 2
        LARGE = 3
        FULL = 4

    template_name = "staff/cards/card.html"
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

    # By default a card doesn't care about dates.
    # Use True to use the page date range.
    # Use an alias to use a fixed date range.
    datetime_range: bool | DatetimeRange | DatetimeRangeAliases = False

    # These will be accessible at render time
    view: View
    request: HttpRequest
    current_datetime_range: DatetimeRange | None

    def render(self, view, request, datetime_range):
        self.view = view
        self.request = request

        if self.datetime_range is True:
            self.current_datetime_range = datetime_range
        elif isinstance(self.datetime_range, DatetimeRangeAliases):
            self.current_datetime_range = DatetimeRangeAliases.to_range(
                self.datetime_range
            )
        elif isinstance(self.datetime_range, DatetimeRange):
            self.current_datetime_range = self.datetime_range
        else:
            self.current_datetime_range = None

        return Template(self.template_name).render(self.get_template_context())

    @classmethod
    def view_name(cls) -> str:
        return f"card_{cls.get_slug()}"

    def get_template_context(self):
        context = {}
        context["title"] = self.get_title()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["number"] = self.get_number()
        context["text"] = self.get_text()
        context["link"] = self.get_link()
        context["datetime_range"] = self.datetime_range
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
