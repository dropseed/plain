from jinja2 import Environment, StrictUndefined

from bolt.runtime import settings
from pathlib import Path
import functools
from bolt.apps import apps
from bolt.runtime import settings
from bolt.utils.module_loading import module_has_submodule
from importlib import import_module

from .filters import default_filters
from .globals import default_globals
from .components import FileSystemTemplateComponentsLoader


@functools.lru_cache
def _get_app_template_dirs():
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


def finalize_callable_error(obj):
    """Prevent direct rendering of a callable (likely just forgotten ()) by raising a TypeError"""
    if callable(obj):
        raise TypeError(f"{obj} is callable, did you forget parentheses?")

    # TODO find a way to prevent <object representation> from being rendered
    # if obj.__class__.__str__ is object.__str__:
    #     raise TypeError(f"{obj} does not have a __str__ method")

    return obj


def get_template_dirs():
    return (settings.path.parent / "templates",) + _get_app_template_dirs()


def create_default_environment(include_apps=True, **environment_kwargs):
    """
    This default jinja environment, also used by the error rendering and internal views so
    customization needs to happen by using this function, not settings that hook in internally.
    """
    kwargs = {
        "loader": FileSystemTemplateComponentsLoader(get_template_dirs()),
        "autoescape": True,
        "auto_reload": settings.DEBUG,
        "undefined": StrictUndefined,
        "finalize": finalize_callable_error,
        "extensions": ["jinja2.ext.loopcontrols", "jinja2.ext.debug"],
    }
    kwargs.update(**environment_kwargs)
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
