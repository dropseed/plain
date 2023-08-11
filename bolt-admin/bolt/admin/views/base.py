from typing import TYPE_CHECKING

from django.core.paginator import Paginator
from django.db import models

from bolt.views import AuthViewMixin, CreateView, DeleteView, TemplateView, UpdateView

from .registry import registry

if TYPE_CHECKING:
    from .panels import AdminPanelView


URL_NAMESPACE = "boltadmin"


class BaseAdminView(AuthViewMixin, TemplateView):
    staff_required = True

    title: str
    slug: str
    path: str = ""
    description: str = ""

    show_in_nav: bool = True

    @classmethod
    def view_name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def get_path(cls) -> str:
        return cls.path or cls.slug


class AdminPageView(BaseAdminView):
    template_name = "bolt/admin/page.html"
    icon: str = ""
    panels: list["AdminPanelView"] = []

    def get_context(self):
        context = super().get_context()
        context["title"] = self.title
        context["slug"] = self.slug
        context["description"] = self.description
        context["icon"] = self.icon
        context["admin_registry"] = registry
        context["panels"] = self.get_panels()
        context["render_panel"] = self.render_panel
        return context

    def get_panels(self):
        return self.panels

    @classmethod
    def view_name(cls) -> str:
        return f"view_{cls.slug}"

    def render_panel(self, panel: "AdminPanelView"):
        """Render panel as a subview"""
        response = panel.as_view()(self.request)
        response.render()
        content = response.content.decode()
        return content


class AdminObjectsView(AdminPageView):
    template_name = "bolt/admin/objects.html"
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

        return context

    def get_objects(self) -> list:
        return []


class AdminUpdateView(AdminPageView, UpdateView):
    show_in_nav = False
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"bolt/admin/{object_meta.app_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminCreateView(AdminPageView, CreateView):
    show_in_nav = False
    template_name = None

    def get_template_names(self) -> list[str]:
        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            return [
                f"bolt/admin/{object_meta.app_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ]

        return super().get_template_names()


class AdminDeleteView(AdminPageView, DeleteView):
    show_in_nav = False
    template_name = "bolt/admin/confirm_delete.html"
