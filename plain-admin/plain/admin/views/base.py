from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.auth.views import AuthView
from plain.runtime import settings
from plain.urls import reverse
from plain.utils import timezone
from plain.views import (
    TemplateView,
)

from ..models import PinnedNavItem
from ..utils import get_gravatar_url
from .registry import registry, track_recent_nav
from .types import Img

if TYPE_CHECKING:
    from plain.http import ResponseBase

    from ..cards import Card
    from .viewsets import AdminViewset


_URL_NAMESPACE = "admin"


class AdminView(AuthView, TemplateView):
    admin_required = True

    title: str = ""
    description: str = ""  # Optional description shown below the title
    path: str = ""
    image: Img | None = None

    # Leave empty to hide from nav
    #
    # An explicit disabling of showing this url/page in the nav
    # which importantly effects the (future) recent pages list
    # so you can also use this for pages that can never be bookmarked
    nav_title = ""
    nav_section = ""
    nav_icon = ""  # Bootstrap Icons name (e.g., "cart", "person", "flag")

    links: dict[str, str] = {}

    parent_view_class: AdminView | None = None

    # Set dynamically by AdminViewset.get_views()
    viewset: type[AdminViewset] | None = None

    template_name = "admin/page.html"
    cards: list[Card] = []

    def get_response(self) -> ResponseBase:
        # Track this page visit for recent nav tabs
        if self.nav_section is not None:
            track_recent_nav(self.request, self.get_slug())

        response = super().get_response()
        response.headers["Cache-Control"] = (
            "no-cache, no-store, must-revalidate, max-age=0"
        )

        return response

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["title"] = self.get_title()
        context["description"] = self.get_description()
        context["image"] = self.get_image()
        context["slug"] = self.get_slug()
        context["links"] = self.get_links()
        context["parent_view_classes"] = self.get_parent_view_classes()
        context["admin_registry"] = registry
        context["cards"] = self.get_cards()
        context["render_card"] = lambda card: card().render(self, self.request)
        context["time_zone"] = timezone.get_current_timezone_name()
        context["view_class"] = self.__class__
        context["app_name"] = settings.NAME
        context["get_gravatar_url"] = get_gravatar_url
        context["nav_tabs"] = registry.get_nav_tabs(self.request)
        context["pinned_slugs"] = set(
            PinnedNavItem.query.filter(user=self.user).values_list(
                "view_slug", flat=True
            )
        )

        return context

    @classmethod
    def view_name(cls) -> str:
        return f"view_{cls.get_slug()}"

    @classmethod
    def get_slug(cls) -> str:
        return f"{cls.__module__}.{cls.__qualname__}".lower().replace(".", "_")

    # Can actually use @classmethod, @staticmethod or regular method for these?
    def get_title(self) -> str:
        return self.title

    def get_description(self) -> str:
        return self.description

    def get_image(self) -> Img | None:
        return self.image

    @classmethod
    def get_path(cls) -> str:
        return cls.path

    @classmethod
    def get_parent_view_classes(cls) -> list[AdminView]:
        parents = []
        parent = cls.parent_view_class
        while parent:
            parents.append(parent)
            parent = parent.parent_view_class
        return parents

    @classmethod
    def get_nav_title(cls) -> str:
        if cls.nav_title:
            return cls.nav_title

        if cls.title:
            return cls.title

        raise NotImplementedError(
            f"Please set a title or nav_title on the {cls} class or implement get_nav_title()."
        )

    @classmethod
    def get_view_url(cls, obj: Any = None) -> str:
        # Check if this view's path expects an id parameter
        if obj and "<int:id>" in cls.get_path():
            return reverse(f"{_URL_NAMESPACE}:" + cls.view_name(), id=obj.id)
        else:
            return reverse(f"{_URL_NAMESPACE}:" + cls.view_name())

    def get_links(self) -> dict[str, str]:
        return self.links.copy()

    def get_cards(self) -> list[Card]:
        return self.cards.copy()
