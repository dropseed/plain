from typing import TYPE_CHECKING

from bolt.http import HttpResponse, HttpResponseNotAllowed
from bolt.db import models
from bolt.paginator import Paginator
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
    from .cards import AdminCardView


URL_NAMESPACE = "admin"


class BaseAdminView(AuthViewMixin, TemplateView):
    staff_required = True

    title: str
    slug: str = ""
    path: str = ""
    description: str = ""
    icon_name = "dot"

    # An explicit disabling of showing this url/page in the nav
    # which importantly effects the (future) recent pages list
    # so you can also use this for pages that can never be bookmarked
    show_in_nav: bool = True

    links: dict[str] = {}

    parent_view_class: "BaseAdminView" = None

    def get_context(self):
        context = super().get_context()
        context["title"] = self.title
        context["slug"] = self.get_slug()
        context["description"] = self.description
        context["icon_name"] = self.icon_name
        context["links"] = self.get_links()
        context["parent_view_classes"] = self.get_parent_view_classes()
        return context

    @classmethod
    def view_name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def get_slug(cls) -> str:
        return cls.slug or slugify(cls.title)

    @classmethod
    def get_path(cls) -> str:
        return cls.path or cls.get_slug()

    @classmethod
    def get_parent_view_classes(cls) -> list["BaseAdminView"]:
        parents = []
        parent = cls.parent_view_class
        while parent:
            parents.append(parent)
            parent = parent.parent_view_class
        return parents

    @classmethod
    def should_show_in_nav(cls) -> bool:
        if not cls.show_in_nav:
            return False

        if cls.parent_view_class:
            # Don't show child views by default
            return False

        return True

    def get_links(self) -> dict[str]:
        return self.links


class AdminPageView(BaseAdminView):
    template_name = "admin/page.html"
    icon: str = ""
    cards: list["AdminCardView"] = []

    def get_context(self):
        context = super().get_context()
        context["icon"] = self.icon
        context["admin_registry"] = registry
        context["cards"] = self.get_cards()
        context["render_card"] = self.render_card
        return context

    def get_cards(self):
        return self.cards

    @classmethod
    def view_name(cls) -> str:
        return f"view_{cls.get_slug()}"

    def render_card(self, card: "AdminCardView"):
        """Render card as a subview"""
        response = card.as_view()(self.request)
        response.render()
        content = response.content.decode()
        return content


class AdminListView(AdminPageView):
    template_name = "admin/list.html"
    list_fields: list
    list_actions: dict[str] = {}
    page_size = 100
    show_search = False

    def get_context(self):
        context = super().get_context()
        context["paginator"] = Paginator(self.get_objects(), self.page_size)
        context["page"] = context["paginator"].get_page(self.request.GET.get("page", 1))
        context["objects"] = context["page"]  # alias
        context["list_fields"] = self.list_fields
        context["list_actions"] = self.list_actions

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
        if action_key and action_key in self.list_actions:
            action_callable = self.list_actions[action_key]
            if isinstance(action_callable, str):
                action_callable = getattr(self, action_callable)
            return action_callable(self.request.POST.getlist("action_pks"))

        raise ValueError("Invalid action")

    def get_objects(self) -> list:
        return []

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


class AdminDetailView(AdminPageView, DetailView):
    template_name = None

    def get_context(self):
        context = super().get_context()
        context["get_object_field"] = self.get_object_field
        return context

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()

    def get_object_field(self, obj, field: str):
        return getattr(obj, field)


class AdminUpdateView(AdminPageView, UpdateView):
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminCreateView(AdminPageView, CreateView):
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminDeleteView(AdminPageView, DeleteView):
    show_in_nav = False  # Never want this to show
    template_name = "admin/confirm_delete.html"
