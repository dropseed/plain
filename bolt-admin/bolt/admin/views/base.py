from typing import TYPE_CHECKING

from bolt.db import models
from bolt.http import HttpResponse
from bolt.paginator import Paginator
from bolt.urls import reverse
from bolt.utils.text import slugify
from bolt.views import (
    AuthViewMixin,
    CreateView,
    DeleteView,
    DetailView,
    TemplateView,
    UpdateView,
)

from .registry import registry

if TYPE_CHECKING:
    from ..cards import Card


URL_NAMESPACE = "admin"


class AdminView(AuthViewMixin, TemplateView):
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

    parent_view_class: "AdminView" = None

    template_name = "admin/page.html"
    cards: list["Card"] = []

    def get_context(self):
        context = super().get_context()
        context["title"] = self.get_title()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["links"] = self.get_links()
        context["parent_view_classes"] = self.get_parent_view_classes()
        context["admin_registry"] = registry
        context["cards"] = self.get_cards()
        context["render_card"] = self.render_card
        return context

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
    def get_parent_view_classes(cls) -> list["AdminView"]:
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
        return self.links

    def get_cards(self):
        return self.cards

    def render_card(self, card: "Card"):
        """Render card as a subview"""
        # response = card.as_view()(self.request)
        # response.render()
        # content = response.content.decode()
        return card().render(self.request)


class AdminListView(AdminView):
    template_name = "admin/list.html"
    fields: list
    actions: dict[str] = {}
    filters: list[str] = []
    page_size = 100
    show_search = False

    def get_context(self):
        context = super().get_context()

        # Make this available on self for usage in get_objects and other methods
        self.filter = self.request.GET.get("filter", "")

        objects = self.get_objects()

        context["paginator"] = Paginator(objects, self.page_size)
        context["page"] = context["paginator"].get_page(self.request.GET.get("page", 1))
        context["objects"] = context["page"]  # alias
        context["fields"] = self.get_fields()
        context["actions"] = self.get_actions()
        context["filters"] = self.get_filters()

        context["active_filter"] = self.filter

        # Implement search yourself in get_objects
        context["search_query"] = self.request.GET.get("search", "")
        context["show_search"] = self.show_search

        context["get_object_pk"] = self.get_object_pk
        context["get_object_field"] = self.get_object_field

        context["get_create_url"] = self.get_create_url
        context["get_detail_url"] = self.get_detail_url
        context["get_update_url"] = self.get_update_url

        return context

    def post(self) -> HttpResponse:
        action_key = self.request.POST.get("action_key")
        actions = self.get_actions()
        if action_key and action_key in actions:
            action_callable = actions[action_key]
            if isinstance(action_callable, str):
                action_callable = getattr(self, action_callable)
            return action_callable(self.request.POST.getlist("action_pks"))

        raise ValueError("Invalid action")

    def get_objects(self) -> list:
        return []

    def get_fields(self) -> list:
        return self.fields

    def get_actions(self) -> dict[str]:
        return self.actions

    def get_filters(self) -> list[str]:
        return self.filters

    def get_object_field(self, obj, field: str):
        # Try basic dict lookup first
        if field in obj:
            return obj[field]

        # Try dot notation
        if "." in field:
            field, subfield = field.split(".", 1)
            return self.get_object_field(obj[field], subfield)

        # Try regular object attribute
        return getattr(obj, field)

    def get_object_pk(self, obj):
        try:
            return self.get_object_field(obj, "pk")
        except AttributeError:
            return self.get_object_field(obj, "id")

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, object) -> str | None:
        return None

    def get_update_url(self, object) -> str | None:
        return None


class AdminDetailView(AdminView, DetailView):
    template_name = None

    def get_context(self):
        context = super().get_context()
        context["get_object_field"] = self.get_object_field
        return context

    def get_template_names(self) -> list[str]:
        # TODO move these to model views
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()

    def get_object_field(self, obj, field: str):
        return getattr(obj, field)


class AdminUpdateView(AdminView, UpdateView):
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminCreateView(AdminView, CreateView):
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminDeleteView(AdminView, DeleteView):
    show_in_nav = False  # Never want this to show
    template_name = "admin/confirm_delete.html"
