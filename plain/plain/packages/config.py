from __future__ import annotations

import os
from functools import cached_property
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from plain.packages.registry import PackagesRegistry

CONFIG_MODULE_NAME = "config"


class PackageConfig:
    """Class representing a Plain application and its configuration."""

    package_label: str

    def __init__(self, name: str):
        # Full Python path to the application e.g. 'plain.admin.admin'.
        self.name = name

        # Reference to the Packages registry that holds this PackageConfig. Set by the
        # registry when it registers the PackageConfig instance.
        self.packages: PackagesRegistry | None = None

        if not hasattr(self, "package_label"):
            # Last component of the Python path to the application e.g. 'admin'.
            # This value must be unique across a Plain project.
            self.package_label = self.name.rpartition(".")[2]

        if not self.package_label.isidentifier():
            raise ImproperlyConfigured(
                f"The app label '{self.package_label}' is not a valid Python identifier."
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.package_label}>"

    @cached_property
    def path(self) -> str:
        # Filesystem path to the application directory e.g.
        # '/path/to/admin'.
        def _path_from_module(module: ModuleType) -> str:
            """Attempt to determine app's filesystem path from its module."""
            # See #21874 for extended discussion of the behavior of this method in
            # various cases.
            # Convert to list because __path__ may not support indexing.
            paths = list(getattr(module, "__path__", []))
            if len(paths) != 1:
                filename = getattr(module, "__file__", None)
                if filename is not None:
                    paths = [os.path.dirname(filename)]
                else:
                    # For unknown reasons, sometimes the list returned by __path__
                    # contains duplicates that must be removed (#25246).
                    paths = list(set(paths))
            if len(paths) > 1:
                raise ImproperlyConfigured(
                    f"The app module {module!r} has multiple filesystem locations ({paths!r}); "
                    "you must configure this app with an PackageConfig subclass "
                    "with a 'path' class attribute."
                )
            elif not paths:
                raise ImproperlyConfigured(
                    f"The app module {module!r} has no filesystem location, "
                    "you must configure this app with an PackageConfig subclass "
                    "with a 'path' class attribute."
                )
            return paths[0]

        module = import_module(self.name)
        return _path_from_module(module)

    def ready(self) -> None:
        """
        Override this method in subclasses to run code when Plain starts.
        """
        return None
