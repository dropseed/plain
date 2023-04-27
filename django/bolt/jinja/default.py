from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jinja2.utils import htmlsafe_json_dumps
from django.conf import settings
from pathlib import Path
import functools
from django.apps import apps
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from django.core.paginator import Paginator
from django.utils.formats import date_format, time_format
from django.conf import settings
from itertools import islice
from django.utils.timesince import timeuntil, timesince
from django.utils.module_loading import import_string, module_has_submodule
from importlib import import_module

def json_script(value, id):
    return format_html(
        '<script type="application/json" id="{}">{}</script>',
        id,
        htmlsafe_json_dumps(value),
    )


def url(viewname, *args, **kwargs):
    # A modified reverse that lets you pass args directly, excluding urlconf
    return reverse(viewname, args=args, kwargs=kwargs)


def get_default_environment_globals():
    return {
        "static": static,
        "url": url,
        "Paginator": Paginator,
    }


def get_default_environment_filters():
    # Filters have more/easier access to context?
    return {
        "json_script": json_script,
        "date": date_format,
        "time": time_format,
        "timeuntil": timeuntil,
        "timesince": timesince,
        "islice": islice,  # slice for dict.items()
    }


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


def _get_app_jinja_attribute(app_config, attribute_name):
    if module_has_submodule(app_config.module, "jinja"):
        mod = import_module(f"{app_config.name}.jinja")
        return getattr(mod, attribute_name, None)


def get_app_extensions():
    """Automatically load {app}.jinja.extensions from INSTALLED_APPS"""
    extensions = []

    for app_config in apps.get_app_configs():
        if app_extensions := _get_app_jinja_attribute(app_config, "extensions"):
            extensions.extend(app_extensions)

    return extensions


def get_app_globals():
    """Automatically load {app}.jinja.globals from INSTALLED_APPS"""
    globals = {}

    for app_config in apps.get_app_configs():
        if app_globals := _get_app_jinja_attribute(app_config, "globals"):
            globals.update(app_globals)

    return globals


def get_app_filters():
    """Automatically load {app}.jinja.filters from INSTALLED_APPS"""
    filters = {}

    for app_config in apps.get_app_configs():
        if app_filters := _get_app_jinja_attribute(app_config, "filters"):
            filters.update(app_filters)

    return filters


def get_default_environment(extra_kwargs={}):
    kwargs = get_default_environment_kwargs()
    kwargs.update(extra_kwargs)

    env = Environment(**kwargs)

    # Load the top-level defaults
    env.globals.update(get_default_environment_globals())
    env.filters.update(get_default_environment_filters())

    # Load from installed apps
    for extension in get_app_extensions():
        env.add_extension(extension)

    env.globals.update(get_app_globals())
    env.filters.update(get_app_filters())

    return env
