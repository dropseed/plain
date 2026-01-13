import functools
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined
from jinja2.loaders import FileSystemLoader

from plain.packages import packages_registry
from plain.runtime import settings

from .filters import default_filters
from .globals import default_globals


def _finalize_callable_error(obj: Any) -> Any:
    """Prevent direct rendering of a callable (likely just forgotten ()) by raising a TypeError"""
    if callable(obj):
        raise TypeError(f"{obj} is callable, did you forget parentheses?")

    # TODO find a way to prevent <object representation> from being rendered
    # if obj.__class__.__str__ is object.__str__:
    #     raise TypeError(f"{obj} does not have a __str__ method")

    return obj


def get_template_dirs() -> tuple[Path, ...]:
    jinja_templates = Path(__file__).parent / "templates"
    app_templates = settings.path.parent / "templates"
    return (jinja_templates, app_templates) + _get_app_template_dirs()


@functools.lru_cache
def _get_app_template_dirs() -> tuple[Path, ...]:
    """
    Return an iterable of paths of directories to load app templates from.

    dirname is the name of the subdirectory containing templates inside
    installed applications.
    """
    dirname = "templates"
    template_dirs = [
        Path(package_config.path) / dirname
        for package_config in packages_registry.get_package_configs()
        if package_config.path and (Path(package_config.path) / dirname).is_dir()
    ]
    # Immutable return value because it will be cached and shared by callers.
    return tuple(template_dirs)


class DefaultEnvironment(Environment):
    def __init__(self):
        super().__init__(
            loader=FileSystemLoader(get_template_dirs()),
            autoescape=True,
            auto_reload=settings.DEBUG,
            undefined=StrictUndefined,
            finalize=_finalize_callable_error,
            extensions=["jinja2.ext.loopcontrols", "jinja2.ext.debug"],
        )

        # Load the top-level defaults
        self.globals.update(default_globals)
        self.filters.update(default_filters)
