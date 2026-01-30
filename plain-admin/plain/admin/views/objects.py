from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain.htmx.views import HTMXView
from plain.http import RedirectResponse, Response
from plain.models import Model, QuerySet
from plain.paginator import Paginator
from plain.views import (
    CreateView,
    DeleteView,
    DetailView,
    UpdateView,
)

from .base import AdminView

if TYPE_CHECKING:
    from plain.forms import BaseForm


def get_field_label(field: str) -> str:
    """Convert snake_case field names to human-readable labels.

    Handles:
    - Double underscore notation for lookups (e.g., created_at__date -> Created At)
    - Dot notation for related fields (e.g., user.email -> User Email)
    - Snake_case to Title Case conversion
    """
    # Handle double underscore notation for related fields (e.g., created_at__date)
    if "__" in field:
        parts = field.split("__")
        # Only take the first part for display
        field = parts[0]

    # Handle dot notation for related fields
    if "." in field:
        parts = field.split(".")
        return " ".join(get_field_label(part) for part in parts)

    # Convert snake_case to Title Case
    return field.replace("_", " ").title()


class AdminListView(HTMXView, AdminView):
    template_name = "admin/list.html"
    fields: list[str] = []
    search_fields: list[str] = []
    actions: list[str] = []
    filters: list[str] = []
    page_size = 20
    allow_global_search = False

    @cached_property
    def filter(self) -> str:
        """Get the current filter parameter from the request."""
        return self.request.query_params.get("filter", "")

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()

        # Make this available to get_filters and stuff
        self.objects = self.process_objects()

        page_size = self.request.query_params.get("page_size", self.page_size)
        paginator = Paginator(self.objects, int(page_size))
        self._page = paginator.get_page(self.request.query_params.get("page", 1))

        context["paginator"] = paginator
        context["page"] = self._page
        context["objects"] = self._page  # alias
        context["fields"] = self.get_fields()
        context["actions"] = self.get_actions()
        context["filters"] = self.get_filters()

        context["current_filter"] = self.filter

        context["search_query"] = self.request.query_params.get("search", "")
        context["search_fields"] = self.search_fields

        context["table_style"] = getattr(self, "_table_style", "default")

        context["get_object_id"] = self.get_object_id
        context["get_field_value"] = self.get_field_value
        context["format_field_value"] = self.format_field_value
        context["get_field_value_template"] = self.get_field_value_template
        context["get_field_label"] = get_field_label

        context["get_object_url"] = self.get_object_url
        context["get_object_links"] = self.get_object_links

        # Sorting
        order_by = self.request.query_params.get("order_by", "")
        if order_by.startswith("-"):
            context["order_by_field"] = order_by[1:]
            context["order_by_direction"] = "-"
        else:
            context["order_by_field"] = order_by
            context["order_by_direction"] = ""

        return context

    def get(self) -> Response:
        if self.is_htmx_request():
            htmx_search = "/search/" in self.request.headers.get("HX-Current-Url", "")
            if htmx_search:
                self._table_style = "preview"
        else:
            htmx_search = False

        response = super().get()

        if self.is_htmx_request() and htmx_search and not self._page:
            # Don't render anything
            return Response(status_code=204)

        return response

    def post(self) -> Response:
        # won't be "key" anymore, just list
        action_name = self.request.form_data.get("action_name")
        actions = self.get_actions()
        if action_name and action_name in actions:
            action_ids_param = self.request.form_data["action_ids"]
            if action_ids_param == "__all__":
                target_ids = [self.get_object_id(obj) for obj in self.process_objects()]
            else:
                target_ids = action_ids_param.split(",") if action_ids_param else []
            response = self.perform_action(action_name, target_ids)
            if response:
                return response
            else:
                # message in session first
                return RedirectResponse(".")

        raise ValueError("Invalid action")

    def perform_action(self, action: str, target_ids: list) -> Response | None:
        raise NotImplementedError

    def process_objects(self) -> list[Any] | QuerySet[Any]:
        objects = self.get_initial_objects()
        objects = self.filter_objects(objects)
        objects = self.search_objects(objects)
        objects = self.order_objects(objects)
        return objects

    def get_initial_objects(self) -> list[Any] | QuerySet[Any]:
        return []

    def filter_objects(
        self, objects: list[Any] | QuerySet[Any]
    ) -> list[Any] | QuerySet[Any]:
        """Filter objects by the current scope. Override to implement scope logic."""
        return objects

    def search_objects(
        self, objects: list[Any] | QuerySet[Any]
    ) -> list[Any] | QuerySet[Any]:
        """Filter a list of objects by the search query param."""
        if search := self.request.query_params.get("search"):
            search = search.lower()
            objects = [
                obj
                for obj in objects
                if any(
                    search in str(self.get_field_value(obj, f)).lower()
                    for f in self.search_fields
                )
            ]
        return objects

    def order_objects(
        self, objects: list[Any] | QuerySet[Any]
    ) -> list[Any] | QuerySet[Any]:
        """Sort a list of objects by the order_by query param."""
        if order_by := self.request.query_params.get("order_by"):
            reverse = order_by.startswith("-")
            field_name = order_by.lstrip("-")
            if field_name in self.get_fields():

                def _sort_key(obj: Any) -> tuple[int, Any]:
                    value = self.get_field_value(obj, field_name)
                    if value is None:
                        # Always sort None last, regardless of direction
                        return (0, "") if reverse else (1, "")
                    return (1, value) if reverse else (0, value)

                objects = sorted(
                    objects,
                    key=_sort_key,
                    reverse=reverse,
                )
        return objects

    def get_fields(self) -> list:
        return (
            self.fields.copy()
        )  # Avoid mutating the class attribute if using append etc

    def get_actions(self) -> list[str]:
        return self.actions.copy()  # Avoid mutating the class attribute itself

    def get_filters(self) -> list[str]:
        return self.filters.copy()  # Avoid mutating the class attribute itself

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

    def get_object_id(self, obj: Any) -> Any:
        return self.get_field_value(obj, "id")

    def get_field_value_template(self, obj: Any, field: str, value: Any) -> list[str]:
        type_str = type(value).__name__.lower()
        return [
            f"admin/values/{type_str}.html",  # Create a template per-type
            f"admin/values/{field}.html",  # Or for specific field names
            "admin/values/default.html",
        ]

    def get_list_url(self) -> str:
        return ""

    def get_create_url(self) -> str:
        return ""

    def get_detail_url(self, obj: Any) -> str:
        return ""

    def get_update_url(self, obj: Any) -> str:
        return ""

    def get_delete_url(self, obj: Any) -> str:
        return ""

    def get_object_url(self, obj: Any) -> str:
        if url := self.get_detail_url(obj):
            return url
        if url := self.get_update_url(obj):
            return url
        if url := self.get_delete_url(obj):
            return url
        return ""

    def get_object_links(self, obj: Any) -> dict[str, str]:
        links = {}
        if self.get_detail_url(obj):
            links["Detail"] = self.get_detail_url(obj)
        if self.get_update_url(obj):
            links["Edit"] = self.get_update_url(obj)
        if self.get_delete_url(obj):
            links["Delete"] = self.get_delete_url(obj)
        return links

    def get_links(self) -> dict[str, str]:
        links = super().get_links()

        # Not tied to a specific object
        if create_url := self.get_create_url():
            links["New"] = create_url

        return links


class AdminCreateView(AdminView, CreateView):
    template_name = None
    nav_section = None

    def get_list_url(self) -> str:
        return ""

    def get_create_url(self) -> str:
        return ""

    def get_detail_url(self, obj: Any) -> str:
        return ""

    def get_update_url(self, obj: Any) -> str:
        return ""

    def get_delete_url(self, obj: Any) -> str:
        return ""

    def get_success_url(self, form: "BaseForm") -> str:
        if list_url := self.get_list_url():
            return list_url

        return super().get_success_url(form)


class AdminDetailView(AdminView, DetailView):
    template_name = None
    nav_section = None
    fields: list[str] = []

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["get_field_value"] = self.get_field_value
        context["format_field_value"] = self.format_field_value
        context["get_field_value_template"] = self.get_field_value_template
        context["get_field_label"] = get_field_label
        context["fields"] = self.get_fields()
        return context

    def get_template_names(self) -> list[str]:
        return super().get_template_names() + [
            "admin/detail.html",  # A generic detail view for rendering any object
        ]

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
        """Format a field value for display. Override this for display formatting."""
        return value

    def get_field_value_template(self, obj: Any, field: str, value: Any) -> list[str]:
        templates = []

        # By type name
        type_str = type(value).__name__.lower()
        templates.append(f"admin/values/{type_str}.html")

        # By field name
        templates.append(f"admin/values/{field}.html")

        # As any model
        if isinstance(value, Model):
            templates.append("admin/values/model.html")

        # Default
        templates.append("admin/values/default.html")

        return templates

    def get_list_url(self) -> str:
        return ""

    def get_create_url(self) -> str:
        return ""

    def get_detail_url(self, obj: Any) -> str:
        return ""

    def get_update_url(self, obj: Any) -> str:
        return ""

    def get_delete_url(self, obj: Any) -> str:
        return ""

    def get_fields(self) -> list[str]:
        return self.fields.copy()  # Avoid mutating the class attribute itself

    def get_links(self) -> dict[str, str]:
        links = super().get_links()

        if hasattr(self.object, "get_absolute_url"):
            links["View in app"] = self.object.get_absolute_url()

        if update_url := self.get_update_url(self.object):
            links["Edit"] = update_url

        if delete_url := self.get_delete_url(self.object):
            links["Delete"] = delete_url

        return links


class AdminUpdateView(AdminView, UpdateView):
    template_name = None
    nav_section = None

    def get_list_url(self) -> str:
        return ""

    def get_create_url(self) -> str:
        return ""

    def get_detail_url(self, obj: Any) -> str:
        return ""

    def get_update_url(self, obj: Any) -> str:
        return ""

    def get_delete_url(self, obj: Any) -> str:
        return ""

    def get_links(self) -> dict[str, str]:
        links = super().get_links()

        if hasattr(self.object, "get_absolute_url"):
            links["View in app"] = self.object.get_absolute_url()

        if detail_url := self.get_detail_url(self.object):
            links["Detail"] = detail_url

        if delete_url := self.get_delete_url(self.object):
            links["Delete"] = delete_url

        return links

    def get_success_url(self, form: "BaseForm") -> str:
        if detail_url := self.get_detail_url(self.object):
            return detail_url

        if list_url := self.get_list_url():
            return list_url

        if update_url := self.get_update_url(self.object):
            return update_url

        return super().get_success_url(form)


class AdminDeleteView(AdminView, DeleteView):
    template_name = "admin/delete.html"
    nav_section = None

    def get_list_url(self) -> str:
        return ""

    def get_create_url(self) -> str:
        return ""

    def get_detail_url(self, obj: Any) -> str:
        return ""

    def get_update_url(self, obj: Any) -> str:
        return ""

    def get_delete_url(self, obj: Any) -> str:
        return ""

    def get_links(self) -> dict[str, str]:
        links = super().get_links()

        if hasattr(self.object, "get_absolute_url"):
            links["View in app"] = self.object.get_absolute_url()

        if detail_url := self.get_detail_url(self.object):
            links["Detail"] = detail_url

        if update_url := self.get_update_url(self.object):
            links["Edit"] = update_url

        return links

    def get_success_url(self, form: "BaseForm") -> str:
        if list_url := self.get_list_url():
            return list_url

        return super().get_success_url(form)
