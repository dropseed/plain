"""Built-in admin views for core functionality."""

from __future__ import annotations

import json
from typing import Any

from plain.http import NotFoundError404, RedirectResponse, Response
from plain.packages import packages_registry
from plain.postgres import QuerySet
from plain.preflight import run_checks, set_check_counts
from plain.runtime import settings as plain_settings

from .models import PinnedNavItem
from .views.base import AdminView
from .views.objects import AdminListView
from .views.registry import registry

MAX_PINNED_ITEMS = 6


class AdminIndexView(AdminView):
    is_builtin = True
    template_name = "admin/index.html"
    title = "Dashboard"

    def get(self) -> Response:
        # Slight hack to redirect to the first view that doesn't
        # require any url params...
        if views := registry.get_list_views(user=self.user):
            return RedirectResponse(list(views)[0].get_view_url())

        return super().get()


class AdminSearchView(AdminView):
    is_builtin = True
    template_name = "admin/search.html"
    title = "Search"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views(user=self.user)
        context["global_search_query"] = self.request.query_params.get("query", "")
        return context


class PinNavView(AdminView):
    """Pin a navigation item for the current user."""

    is_builtin = True
    nav_section = None

    def post(self) -> Response:
        view_slug = self.request.form_data.get("view_slug")
        if not view_slug:
            return Response("view_slug is required", status_code=400)

        # Check if user has reached max pinned items
        current_count = PinnedNavItem.query.filter(user=self.user).count()
        if current_count >= MAX_PINNED_ITEMS:
            return Response(
                f"Maximum of {MAX_PINNED_ITEMS} pinned items reached",
                status_code=400,
            )

        # Verify the view slug exists
        if not registry.get_view_by_slug(view_slug):
            return Response("Invalid view_slug", status_code=400)

        max_order = (
            PinnedNavItem.query.filter(user=self.user)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        next_order = (max_order or 0) + 1

        PinnedNavItem.query.get_or_create(
            user=self.user,
            view_slug=view_slug,
            defaults={"order": next_order},
        )

        # Redirect back to current page (or referer)
        referer = self.request.headers.get("Referer", "/admin/")
        return RedirectResponse(referer, allow_external=True)


class UnpinNavView(AdminView):
    """Unpin a navigation item for the current user."""

    is_builtin = True
    nav_section = None

    def post(self) -> Response:
        view_slug = self.request.form_data.get("view_slug")
        if not view_slug:
            return Response("view_slug is required", status_code=400)

        PinnedNavItem.query.filter(
            user=self.user,
            view_slug=view_slug,
        ).delete()

        # Redirect back to current page (or referer)
        referer = self.request.headers.get("Referer", "/admin/")
        return RedirectResponse(referer, allow_external=True)


class ReorderPinnedView(AdminView):
    """Reorder pinned navigation items."""

    is_builtin = True
    nav_section = None

    def post(self) -> Response:
        slugs_json = self.request.form_data.get("slugs")
        if not slugs_json:
            return Response("slugs is required", status_code=400)

        try:
            slugs = json.loads(slugs_json)
        except json.JSONDecodeError:
            return Response("Invalid slugs JSON", status_code=400)

        # Only update slugs that exist and belong to this user
        user_pinned = set(
            PinnedNavItem.query.filter(user=self.user).values_list(
                "view_slug", flat=True
            )
        )
        for i, slug in enumerate(slugs):
            if slug in user_pinned:
                PinnedNavItem.query.filter(user=self.user, view_slug=slug).update(
                    order=i
                )

        # No redirect needed for drag-and-drop reorder (called via fetch)
        return Response("OK")


def _setting_to_dict(name: str, defn: Any) -> dict[str, Any]:
    return {
        "name": name,
        "source": defn.source,
        "value": defn.display_value(),
        "env_var_name": defn.env_var_name,
        "is_secret": defn.is_secret,
    }


class SettingsView(AdminListView):
    is_builtin = True
    title = "App Settings"
    description = (
        "All framework and app settings with their current values and sources."
    )
    nav_section = None
    fields = ["name", "source", "value"]

    @classmethod
    def get_view_url(cls, obj: Any = None) -> str:
        return "/admin/settings/"

    search_fields = ["name"]
    filters = ["default", "explicit", "env"]
    page_size = 100

    _FIELD_TEMPLATES = {
        "name": ["admin/values/setting_name.html"],
        "source": ["admin/values/setting_source.html"],
        "value": ["admin/values/setting_value.html"],
    }

    def get_initial_objects(self) -> list[dict[str, Any]]:
        return [
            _setting_to_dict(name, defn) for name, defn in plain_settings.get_settings()
        ]

    def filter_objects(
        self, objects: list[Any] | QuerySet[Any]
    ) -> list[Any] | QuerySet[Any]:
        if self.filter:
            return [obj for obj in objects if obj["source"] == self.filter]
        return objects

    def format_field_value(self, obj: Any, field: str, value: Any) -> Any:
        if field == "source" and obj.get("env_var_name"):
            return obj["env_var_name"]
        return value

    def get_detail_url(self, obj: Any) -> str:
        return f"/admin/settings/{obj['name']}/"

    def get_field_value_template(self, obj: Any, field: str, value: Any) -> list[str]:
        if field in self._FIELD_TEMPLATES:
            return self._FIELD_TEMPLATES[field]
        return super().get_field_value_template(obj, field, value)


class SettingDetailView(AdminView):
    is_builtin = True
    template_name = "admin/setting_detail.html"
    parent_view_class = SettingsView
    nav_section = None

    def get_template_context(self) -> dict[str, Any]:
        name = self.url_kwargs["name"]
        settings_map = dict(plain_settings.get_settings())
        defn = settings_map.get(name)
        if defn is None:
            raise NotFoundError404()

        context = super().get_template_context()
        context["title"] = name
        context["setting"] = _setting_to_dict(name, defn)
        return context


class PreflightView(AdminView):
    """Run and display preflight check results."""

    is_builtin = True
    template_name = "admin/preflight.html"
    title = "Preflight"
    description = "System checks that verify your app configuration is correct."
    nav_section = None

    def _run_checks(self) -> tuple[list[dict], int, int, int]:
        """Run all preflight checks and return (checks, passed, warnings, errors)."""
        packages_registry.autodiscover_modules("preflight", include_app=True)

        include_deploy = not plain_settings.DEBUG

        checks = []
        passed_count = 0
        warning_count = 0
        error_count = 0

        for check_class, name, results in run_checks(
            include_deploy_checks=include_deploy
        ):
            issues = []
            for result in results:
                if result.is_silenced():
                    continue
                issues.append(
                    {
                        "fix": result.fix,
                        "id": result.id,
                        "warning": result.warning,
                    }
                )

            has_errors = any(not issue["warning"] for issue in issues)
            if issues:
                if has_errors:
                    error_count += 1
                else:
                    warning_count += 1
            else:
                passed_count += 1

            checks.append(
                {
                    "name": name,
                    "passed": not issues,
                    "has_errors": has_errors,
                    "issues": issues,
                }
            )

        # Refresh the shared cache so badge counts stay current.
        set_check_counts(errors=error_count, warnings=warning_count)

        return checks, passed_count, warning_count, error_count

    def get_template_context(self) -> dict[str, Any]:
        checks, passed_count, warning_count, error_count = self._run_checks()

        total_count = passed_count + warning_count + error_count
        pass_percent = (passed_count / total_count * 100) if total_count else 100

        context = super().get_template_context()
        context["checks"] = checks
        context["passed_count"] = passed_count
        context["warning_count"] = warning_count
        context["error_count"] = error_count
        context["total_count"] = total_count
        context["pass_percent"] = pass_percent
        context["include_deploy"] = not plain_settings.DEBUG
        return context


class StyleGuideView(AdminView):
    """Style guide showing available components and patterns."""

    is_builtin = True
    template_name = "admin/style.html"
    title = "Style Guide"
    nav_section = None
