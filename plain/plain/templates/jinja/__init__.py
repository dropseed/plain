from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plain.packages import packages_registry
from plain.runtime import settings
from plain.utils.functional import LazyObject
from plain.utils.module_loading import import_string

from .environments import DefaultEnvironment, get_template_dirs


class JinjaEnvironment(LazyObject):
    def _setup(self) -> None:
        environment_setting = settings.TEMPLATES_JINJA_ENVIRONMENT

        if isinstance(environment_setting, str):
            env = import_string(environment_setting)()
        else:
            env = environment_setting()

        # We have to set _wrapped before we trigger the autoloading of "register" commands
        self._wrapped = env

        # Autoload template helpers using the registry method
        packages_registry.autodiscover_modules("templates", include_app=True)


environment = JinjaEnvironment()


def register_template_extension(extension_class: type) -> type:
    environment.add_extension(extension_class)
    return extension_class


def register_template_global(value: Any, name: str | None = None) -> Any:
    """
    Adds a global to the Jinja environment.

    Can be used as a decorator on a function:

            @register_template_global
            def my_global():
                return "Hello, world!"

    Or as a function:

            register_template_global("Hello, world!", name="my_global")
    """
    if callable(value):
        environment.globals[name or value.__name__] = value
    elif name:
        environment.globals[name] = value
    else:
        raise ValueError("name must be provided if value is not callable")

    return value


def register_template_filter(
    func: Callable[..., Any], name: str | None = None
) -> Callable[..., Any]:
    """Adds a filter to the Jinja environment."""
    filter_name = name if name is not None else func.__name__  # type: ignore[attr-defined]
    environment.filters[filter_name] = func
    return func


__all__ = [
    "environment",
    "DefaultEnvironment",
    "get_template_dirs",
    "register_template_extension",
    "register_template_filter",
    "register_template_global",
]
