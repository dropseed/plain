from jinja2 import Environment, FileSystemLoader, StrictUndefined

from django.conf import settings
from pathlib import Path
import functools
from django.apps import apps
from django.conf import settings
from django.utils.module_loading import module_has_submodule
from importlib import import_module

from .filters import default_filters
from .globals import default_globals


@functools.lru_cache
def get_app_template_dirs():
    """
    Return an iterable of paths of directories to load app templates from.

    dirname is the name of the subdirectory containing templates inside
    installed applications.
    """
    dirname = "templates"
    template_dirs = [
        Path(app_config.path) / dirname
        for app_config in apps.get_app_configs()
        if app_config.path and (Path(app_config.path) / dirname).is_dir()
    ]
    # Immutable return value because it will be cached and shared by callers.
    return tuple(template_dirs)


def get_default_environment_kwargs():
    template_dirs = (settings.path.parent / "templates",) + get_app_template_dirs()
    return {
        "loader": FileSystemLoader(template_dirs),
        "autoescape": True,
        "auto_reload": settings.DEBUG,
        "undefined": StrictUndefined,
    }


def _get_installed_extensions() -> tuple[list, dict, dict]:
    """Automatically load extensions, globals, filters from INSTALLED_APPS jinja module and root jinja module"""
    extensions = []
    globals = {}
    filters = {}

    for app_config in apps.get_app_configs():
        if module_has_submodule(app_config.module, "jinja"):
            module = import_module(f"{app_config.name}.jinja")
        else:
            continue

        if hasattr(module, "extensions"):
            extensions.extend(module.extensions)

        if hasattr(module, "globals"):
            globals.update(module.globals)

        if hasattr(module, "filters"):
            filters.update(module.filters)

    try:
        import jinja

        if hasattr(jinja, "extensions"):
            extensions.extend(jinja.extensions)

        if hasattr(jinja, "globals"):
            globals.update(jinja.globals)

        if hasattr(jinja, "filters"):
            filters.update(jinja.filters)
    except ImportError:
        pass

    return extensions, globals, filters


def create_default_environment(extra_kwargs={}, include_root=True, include_apps=True):
    kwargs = get_default_environment_kwargs()
    kwargs.update(extra_kwargs)

    env = Environment(**kwargs)

    # Load the top-level defaults
    env.globals.update(default_globals)
    env.filters.update(default_filters)

    if include_apps:
        app_extensions, app_globals, app_filters = _get_installed_extensions()

        for extension in app_extensions:
            env.add_extension(extension)

        env.globals.update(app_globals)
        env.filters.update(app_filters)

    return env
