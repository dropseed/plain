from typing import TYPE_CHECKING

from plain import models
from plain.auth.views import AuthViewMixin
from plain.htmx.views import HTMXViewMixin
from plain.http import Response, ResponseRedirect
from plain.paginator import Paginator
from plain.staff.dates import DatetimeRange, DatetimeRangeAliases
from plain.urls import reverse
from plain.utils import timezone
from plain.utils.text import slugify
from plain.views import (
    CreateView,
    DeleteView,
    DetailView,
    TemplateView,
    UpdateView,
)

from .registry import registry

if TYPE_CHECKING:
    from ..cards import Card


URL_NAMESPACE = "staff"


class StaffView(AuthViewMixin, TemplateView):
    staff_required = True

    title: str
    slug: str = ""
    path: str = ""
    description: str = ""

    # Leave empty to hide from nav
    #
    # An explicit disabling of showing this url/page in the nav
    # which importantly effects the (future) recent pages list
    # so you can also use this for pages that can never be bookmarked
    nav_section = "App"

    links: dict[str] = {}

    parent_view_class: "StaffView" = None

    template_name = "staff/page.html"
    cards: list["Card"] = []

    default_datetime_range = DatetimeRangeAliases.LAST_365_DAYS

    def get_template_context(self):
        context = super().get_template_context()
        context["title"] = self.get_title()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["links"] = self.get_links()
        context["parent_view_classes"] = self.get_parent_view_classes()
        context["admin_registry"] = registry
        context["cards"] = self.get_cards()
        context["render_card"] = self.render_card
        context["from_datetime"] = self.datetime_range.start
        context["to_datetime"] = self.datetime_range.end
        context["time_zone"] = timezone.get_current_timezone_name()
        return context

    def get_response(self):
        default_range = DatetimeRangeAliases.to_range(self.default_datetime_range)
        from_datetime = self.request.GET.get("from", default_range.start)
        to_datetime = self.request.GET.get("to", default_range.end)
        self.datetime_range = DatetimeRange(from_datetime, to_datetime)
        return super().get_response()

    @classmethod
    def view_name(cls) -> str:
        return f"view_{cls.get_slug()}"

    @classmethod
    def get_title(cls) -> str:
        return cls.title

    @classmethod
    def get_slug(cls) -> str:
        return cls.slug or slugify(cls.get_title())

    @classmethod
    def get_description(cls) -> str:
        return cls.description

    @classmethod
    def get_path(cls) -> str:
        return cls.path or cls.get_slug()

    @classmethod
    def get_parent_view_classes(cls) -> list["StaffView"]:
        parents = []
        parent = cls.parent_view_class
        while parent:
            parents.append(parent)
            parent = parent.parent_view_class
        return parents

    @classmethod
    def get_nav_section(cls) -> bool:
        if not cls.nav_section:
            return ""

        if cls.parent_view_class:
            # Don't show child views by default
            return ""

        return cls.nav_section

    @classmethod
    def get_absolute_url(cls) -> str:
        return reverse(f"{URL_NAMESPACE}:" + cls.view_name())

    def get_links(self) -> dict[str]:
        return self.links.copy()

    def get_cards(self):
        return self.cards.copy()

    def render_card(self, card: "Card"):
        """Render card as a subview"""
        # response = card.as_view()(self.request)
        # response.render()
        # content = response.content.decode()
        return card().render(self, self.request, self.datetime_range)


class StaffListView(HTMXViewMixin, StaffView):
    template_name = "staff/list.html"
    fields: list[str]
    actions: list[str] = []
    filters: list[str] = []
    page_size = 100
    show_search = False
    allow_global_search = False

    def get_template_context(self):
        context = super().get_template_context()

        # Make this available on self for usage in get_objects and other methods
        self.filter = self.request.GET.get("filter", "")

        # Make this available to get_filters and stuff
        self.objects = self.get_objects()

        page_size = self.request.GET.get("page_size", self.page_size)
        paginator = Paginator(self.objects, page_size)
        self._page = paginator.get_page(self.request.GET.get("page", 1))

        context["paginator"] = paginator
        context["page"] = self._page
        context["objects"] = self._page  # alias
        context["fields"] = self.get_fields()
        context["actions"] = self.get_actions()
        context["filters"] = self.get_filters()

        context["active_filter"] = self.filter

        # Implement search yourself in get_objects
        context["search_query"] = self.request.GET.get("search", "")
        context["show_search"] = self.show_search

        context["table_style"] = getattr(self, "_table_style", "default")

        context["get_object_pk"] = self.get_object_pk
        context["get_field_value"] = self.get_field_value
        context["get_field_value_template"] = self.get_field_value_template

        context["get_create_url"] = self.get_create_url
        context["get_object_links"] = self.get_object_links

        return context

    def get(self) -> Response:
        if self.is_htmx_request:
            hx_from_this_page = self.request.path in self.request.headers.get(
                "HX-Current-Url", ""
            )
            if not hx_from_this_page:
                self._table_style = "simple"
        else:
            hx_from_this_page = False

        response = super().get()

        if self.is_htmx_request and not hx_from_this_page and not self._page:
            # Don't render anything
            return Response(status=204)

        return response

    def post(self) -> Response:
        # won't be "key" anymore, just list
        action_name = self.request.POST.get("action_name")
        actions = self.get_actions()
        if action_name and action_name in actions:
            target_pks = self.request.POST["action_pks"].split(",")
            response = self.perform_action(action_name, target_pks)
            if response:
                return response
            else:
                # message in session first
                return ResponseRedirect(".")

        raise ValueError("Invalid action")

    def perform_action(self, action: str, target_pks: list) -> Response | None:
        raise NotImplementedError

    def get_objects(self) -> list:
        return []

    def get_fields(self) -> list:
        return (
            self.fields.copy()
        )  # Avoid mutating the class attribute if using append etc

    def get_actions(self) -> dict[str]:
        return self.actions.copy()  # Avoid mutating the class attribute itself

    def get_filters(self) -> list[str]:
        return self.filters.copy()  # Avoid mutating the class attribute itself

    def get_field_value(self, obj, field: str):
        # Try basic dict lookup first
        if field in obj:
            return obj[field]

        # Try dot notation
        if "." in field:
            field, subfield = field.split(".", 1)
            return self.get_field_value(obj[field], subfield)

        # Try regular object attribute
        return getattr(obj, field)

    def get_object_pk(self, obj):
        try:
            return self.get_field_value(obj, "pk")
        except AttributeError:
            return self.get_field_value(obj, "id")

    def get_field_value_template(self, obj, field: str, value):
        type_str = type(value).__name__.lower()
        return [
            f"staff/values/{type_str}.html",  # Create a template per-type
            f"staff/values/{field}.html",  # Or for specific field names
            "staff/values/default.html",
        ]

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, obj) -> str | None:
        return None

    def get_update_url(self, obj) -> str | None:
        return None

    def get_object_links(self, obj) -> dict[str]:
        links = {}
        if self.get_detail_url(obj):
            links["Detail"] = self.get_detail_url(obj)
        if self.get_update_url(obj):
            links["Update"] = self.get_update_url(obj)
        return links


class StaffDetailView(StaffView, DetailView):
    template_name = None
    nav_section = ""

    def get_template_context(self):
        context = super().get_template_context()
        context["get_field_value"] = self.get_field_value
        return context

    def get_template_names(self) -> list[str]:
        # TODO move these to model views
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"staff/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()

    def get_field_value(self, obj, field: str):
        return getattr(obj, field)

    def get_update_url(self, obj) -> str | None:
        return None


class StaffUpdateView(StaffView, UpdateView):
    template_name = None
    nav_section = ""

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"staff/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()

    def get_detail_url(self, obj) -> str | None:
        return None


class StaffCreateView(StaffView, CreateView):
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"staff/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class StaffDeleteView(StaffView, DeleteView):
    template_name = "staff/confirm_delete.html"
    nav_section = ""
