from typing import TYPE_CHECKING

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

    show_in_nav: bool = True

    parent_view_class: "BaseAdminView" = None

    def get_context(self):
        context = super().get_context()
        context["title"] = self.title
        context["slug"] = self.get_slug()
        context["description"] = self.description
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


class AdminObjectsView(AdminPageView):
    template_name = "admin/objects.html"
    list_fields: list
    page_size = 100
    show_search = False

    def get_context(self):
        context = super().get_context()
        context["paginator"] = Paginator(self.get_objects(), self.page_size)
        context["page"] = context["paginator"].get_page(self.request.GET.get("page", 1))
        context["objects"] = context["page"]  # alias
        context["list_fields"] = self.list_fields

        context["search_query"] = self.request.GET.get("search", "")
        context["show_search"] = self.show_search
        context["get_object_field"] = self.get_object_field

        return context

    def get_objects(self) -> list:
        return []

    def get_object_field(self, obj, field: str):
        return getattr(obj, field)


class AdminDetailView(AdminPageView, DetailView):
    show_in_nav = False
    template_name = None

    def get_context(self):
        context = super().get_context()
        context["get_object_field"] = self.get_object_field
        return context

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.app_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()

    def get_object_field(self, obj, field: str):
        return getattr(obj, field)


class AdminUpdateView(AdminPageView, UpdateView):
    show_in_nav = False
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.app_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminCreateView(AdminPageView, CreateView):
    show_in_nav = False
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"admin/{object_meta.app_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminDeleteView(AdminPageView, DeleteView):
    show_in_nav = False
    template_name = "admin/confirm_delete.html"
