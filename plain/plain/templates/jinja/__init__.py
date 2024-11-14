from importlib import import_module

from plain.packages import packages
from plain.runtime import settings
from plain.utils.functional import LazyObject
from plain.utils.module_loading import import_string, module_has_submodule

from .environments import DefaultEnvironment, get_template_dirs


class JinjaEnvironment(LazyObject):
    def __init__(self, *args, **kwargs):
        self.__dict__["_imported_modules"] = set()
        super().__init__(*args, **kwargs)

    def _setup(self):
        environment_setting = settings.TEMPLATES_JINJA_ENVIRONMENT

        if isinstance(environment_setting, str):
            env = import_string(environment_setting)()
        else:
            env = environment_setting()

        # We have to set _wrapped before we trigger the autoloading of "register" commands
        self._wrapped = env

        def _maybe_import_module(name):
            if name not in self._imported_modules:
                import_module(name)
                self._imported_modules.add(name)

        for package_config in packages.get_package_configs():
            if module_has_submodule(package_config.module, "templates"):
                # Allow this to fail in case there are import errors inside of their file
                _maybe_import_module(f"{package_config.name}.templates")

        app = import_module("app")
        if module_has_submodule(app, "templates"):
            # Allow this to fail in case there are import errors inside of their file
            _maybe_import_module("app.templates")


environment = JinjaEnvironment()


def register_template_extension(extension_class):
    environment.add_extension(extension_class)
    return extension_class


def register_template_global(value, name=None):
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


def register_template_filter(func, name=None):
    """Adds a filter to the Jinja environment."""
    environment.filters[name or func.__name__] = func
    return func


__all__ = [
    "environment",
    "DefaultEnvironment",
    "get_template_dirs",
    "register_template_extension",
    "register_template_filter",
    "register_template_global",
]
