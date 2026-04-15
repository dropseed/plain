from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING, Any

import click

from plain.packages import packages_registry

from .loader import MigrationLoader

if TYPE_CHECKING:
    from plain.postgres.fields import Field


class MigrationQuestioner:
    """
    Give the autodetector responses to questions it might have.
    This base class has a built-in noninteractive mode, but the
    interactive subclass is what the command-line arguments will use.
    """

    def __init__(
        self,
        defaults: dict[str, Any] | None = None,
        specified_packages: set[str] | None = None,
        dry_run: bool | None = None,
    ) -> None:
        self.defaults = defaults or {}
        self.specified_packages = specified_packages or set()
        self.dry_run = dry_run

    def ask_initial(self, package_label: str) -> bool:
        """Should we create an initial migration for the app?"""
        # If it was specified on the command line, definitely true
        if package_label in self.specified_packages:
            return True
        # Otherwise, we look to see if it has a migrations module
        # without any Python files in it, apart from __init__.py.
        # Packages from the new app template will have these; the Python
        # file check will ensure we skip South ones.
        try:
            package_config = packages_registry.get_package_config(package_label)
        except LookupError:  # It's a fake app.
            return self.defaults.get("ask_initial", False)
        migrations_import_path, _ = MigrationLoader.migrations_module(
            package_config.package_label
        )
        if migrations_import_path is None:
            # It's an application with migrations disabled.
            return self.defaults.get("ask_initial", False)
        try:
            migrations_module = importlib.import_module(migrations_import_path)
        except ImportError:
            return self.defaults.get("ask_initial", False)
        else:
            if file := getattr(migrations_module, "__file__", None):
                filenames = os.listdir(os.path.dirname(file))
            elif hasattr(migrations_module, "__path__"):
                if len(migrations_module.__path__) > 1:
                    return False
                filenames = os.listdir(list(migrations_module.__path__)[0])
            return not any(x.endswith(".py") for x in filenames if x != "__init__.py")

    def ask_rename(
        self, model_name: str, old_name: str, new_name: str, field_instance: Field
    ) -> bool:
        """Was this field really renamed?"""
        return self.defaults.get("ask_rename", False)

    def ask_rename_model(self, old_model_state: Any, new_model_state: Any) -> bool:
        """Was this model really renamed?"""
        return self.defaults.get("ask_rename_model", False)


class InteractiveMigrationQuestioner(MigrationQuestioner):
    def _boolean_input(self, question: str, default: bool | None = None) -> bool:
        return click.confirm(question, default=default)

    def ask_rename(
        self, model_name: str, old_name: str, new_name: str, field_instance: Field
    ) -> bool:
        """Was this field really renamed?"""
        msg = "Was %s.%s renamed to %s.%s (a %s)?"
        return self._boolean_input(
            msg
            % (
                model_name,
                old_name,
                model_name,
                new_name,
                field_instance.__class__.__name__,
            ),
            default=False,
        )

    def ask_rename_model(self, old_model_state: Any, new_model_state: Any) -> bool:
        """Was this model really renamed?"""
        msg = "Was the model %s.%s renamed to %s?"
        return self._boolean_input(
            msg
            % (
                old_model_state.package_label,
                old_model_state.name,
                new_model_state.name,
            ),
            default=False,
        )
