from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.auth.views import AuthView
from plain.http import ForbiddenError403
from plain.preflight import get_check_counts
from plain.runtime import settings
from plain.urls import reverse
from plain.utils import timezone
from plain.views import (
    TemplateView,
)

from ..models import PinnedNavItem
from .registry import registry, track_recent_nav
from .types import Img

if TYPE_CHECKING:
    from plain.http import ResponseBase
    from plain.postgres import Model

    from ..cards import Card
    from .viewsets import AdminViewset


_URL_NAMESPACE = "admin"


class AdminView(AuthView, TemplateView):
    admin_required = True
    user: Model  # Always set — admin_required guarantees authentication

    # True for framework-provided views (index, search, settings, etc.)
    # Available for use in ADMIN_HAS_PERMISSION to make per-view decisions.
    is_builtin = False

    def check_auth(self) -> None:
        super().check_auth()
        if not self.has_permission(self.user):
            raise ForbiddenError403("You don't have access to this page.")

    @classmethod
    def has_permission(cls, user: Model) -> bool:
        if check := settings.ADMIN_HAS_PERMISSION:
            return check(cls, user)
        return True

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
    extra_links: dict[str, str] = {}
    field_templates: dict[str, str] = {}

    parent_view_class: AdminView | None = None

    # Set dynamically by AdminViewset.get_views()
    viewset: type[AdminViewset] | None = None

    template_name = "admin/page.html"
    cards: list[Card] = []

    def before_request(self) -> None:
        super().before_request()
        # Track this page visit for recent nav tabs
        if self.nav_section is not None:
            track_recent_nav(self.request, self.get_slug())

    def after_response(self, response: ResponseBase) -> ResponseBase:
        response = super().after_response(response)
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
        context["extra_links"] = self.get_extra_links()
        context["parent_view_classes"] = self.get_parent_view_classes()
        context["admin_registry"] = registry
        context["cards"] = self.get_cards()
        context["render_card"] = lambda card: card().render(self, self.request)
        context["time_zone"] = timezone.get_current_timezone_name()
        context["view_class"] = self.__class__
        context["app_name"] = settings.NAME

        context["nav_tabs"] = registry.get_nav_tabs(self.request)
        context["pinned_slugs"] = set(
            PinnedNavItem.query.filter(user=self.user).values_list(
                "view_slug", flat=True
            )
        )
        context["preflight_counts"] = get_check_counts()
        context["admin_url"] = registry.get_url

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

    def get_extra_links(self) -> dict[str, str]:
        return self.extra_links.copy()

    def get_cards(self) -> list[Card]:
        return self.cards.copy()

    def get_field_value(self, obj: Any, field: str) -> Any:
        try:
            # Try basic dict lookup first
            if field in obj:
                return obj[field]
        except TypeError:
            pass

        # Try dot notation
        if "." in field:
            field, subfield = field.split(".", 1)
            return self.get_field_value(obj[field], subfield)

        # Try regular object attribute
        attr = getattr(obj, field)

        # Call if it's callable
        if callable(attr):
            return attr()
        else:
            return attr

    def format_field_value(self, obj: Any, field: str, value: Any) -> Any:
        """Format a field value for display. Override this for display formatting
        like currency symbols, percentages, etc. Sorting and searching use
        get_field_value directly, so formatting here won't affect sort order."""
        return value

    def get_field_value_template(self, obj: Any, field: str, value: Any) -> list[str]:
        templates = []

        # By explicit field_templates mapping
        if field in self.field_templates:
            templates.append(self.field_templates[field])

        # By field name
        templates.append(f"admin/values/{field}.html")

        # By database field type
        try:
            field_obj = obj._model_meta.get_field(field)
            field_type = type(field_obj).__name__
            templates.append(f"admin/values/{field_type}.html")
        except Exception:
            pass

        # By value type (walk MRO for parent classes)
        for cls in type(value).__mro__:
            if cls is object:
                break
            templates.append(f"admin/values/{cls.__name__}.html")

        # Default
        templates.append("admin/values/default.html")

        return templates
