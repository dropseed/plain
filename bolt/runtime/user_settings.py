"""
Settings and configuration for Bolt.

Read values from the module specified by the BOLT_SETTINGS_MODULE environment
variable, and then from bolt.global_settings; see the global_settings.py
for a list of all possible variables.
"""

import importlib
import os
import time
import types
import typing
from pathlib import Path

from bolt.apps import AppConfig
from bolt.exceptions import ImproperlyConfigured
from . import global_settings
from bolt.utils.functional import LazyObject, empty

ENVIRONMENT_VARIABLE = "BOLT_SETTINGS_MODULE"
DEFAULT_STORAGE_ALIAS = "default"
STATICFILES_STORAGE_ALIAS = "staticfiles"


class SettingsReference(str):
    """
    String subclass which references a current settings value. It's treated as
    the value in memory but serializes to a settings.NAME attribute reference.
    """

    def __new__(self, value, setting_name):
        return str.__new__(self, value)

    def __init__(self, value, setting_name):
        self.setting_name = setting_name


class LazySettings(LazyObject):
    """
    A lazy proxy for either global Bolt settings or a custom settings object.
    The user can manually configure settings prior to using them. Otherwise,
    Bolt uses the settings module pointed to by BOLT_SETTINGS_MODULE.
    """

    def _setup(self, name=None):
        """
        Load the settings module pointed to by the environment variable. This
        is used the first time settings are needed, if the user hasn't
        configured settings manually.
        """
        settings_module = os.environ.get(ENVIRONMENT_VARIABLE, "settings")
        self._wrapped = Settings(settings_module)

    def __repr__(self):
        # Hardcode the class name as otherwise it yields 'Settings'.
        if self._wrapped is empty:
            return "<LazySettings [Unevaluated]>"
        return '<LazySettings "{settings_module}">'.format(
            settings_module=self._wrapped.SETTINGS_MODULE,
        )

    def __getattr__(self, name):
        """Return the value of a setting and cache it in self.__dict__."""
        if (_wrapped := self._wrapped) is empty:
            self._setup(name)
            _wrapped = self._wrapped
        val = getattr(_wrapped, name)

        # Special case some settings which require further modification.
        # This is done here for performance reasons so the modified value is cached.
        if name == "SECRET_KEY" and not val:
            raise ImproperlyConfigured("The SECRET_KEY setting must not be empty.")

        self.__dict__[name] = val
        return val

    def __setattr__(self, name, value):
        """
        Set the value of setting. Clear all cached values if _wrapped changes
        (@override_settings does this) or clear single values when set.
        """
        if name == "_wrapped":
            self.__dict__.clear()
        else:
            self.__dict__.pop(name, None)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        """Delete a setting and clear it from cache if needed."""
        super().__delattr__(name)
        self.__dict__.pop(name, None)

    @property
    def configured(self):
        """Return True if the settings have already been configured."""
        return self._wrapped is not empty


class DefaultSetting:
    """Store some basic info about default settings and where they came from"""

    def __init__(self, name, value, annotation, module):
        self.name = name
        self.value = value
        self.annotation = annotation
        self.module = module

    def __str__(self):
        return self.name

    def check_type(self, obj):
        if not self.annotation:
            return

        if not DefaultSetting._is_instance_of_type(obj, self.annotation):
            raise ValueError(
                f"The {self.name} setting must be of type {self.annotation}"
            )

    @staticmethod
    def _is_instance_of_type(value, type_hint) -> bool:
        # Simple types
        if isinstance(type_hint, type):
            return isinstance(value, type_hint)

        # Union types
        if (
            typing.get_origin(type_hint) is typing.Union
            or typing.get_origin(type_hint) is types.UnionType
        ):
            return any(
                DefaultSetting._is_instance_of_type(value, arg)
                for arg in typing.get_args(type_hint)
            )

        # List types
        if typing.get_origin(type_hint) is list:
            return isinstance(value, list) and all(
                DefaultSetting._is_instance_of_type(item, typing.get_args(type_hint)[0])
                for item in value
            )

        raise ValueError("Unsupported type hint: %s" % type_hint)


class Settings:
    def __init__(self, settings_module):
        self._default_settings = {}
        self._load_module_settings(global_settings)

        # store the settings module in case someone later cares
        self.SETTINGS_MODULE = settings_module

        mod = importlib.import_module(self.SETTINGS_MODULE)

        # Keep a reference to the settings.py module path
        # so we can find files next to it (assume it's at the app root)
        self.path = Path(mod.__file__).resolve()

        # Get INSTALLED_APPS from mod,
        # then (without populating apps) do a check for default_settings in each
        # app and load those now too.
        for entry in getattr(mod, "INSTALLED_APPS", []):
            try:
                if isinstance(entry, AppConfig):
                    app_settings = entry.module.default_settings
                else:
                    app_settings = importlib.import_module(f"{entry}.default_settings")
            except ModuleNotFoundError:
                continue

            self._load_module_settings(app_settings)

        self._explicit_settings = set()
        for setting in dir(mod):
            if setting.isupper():
                setting_value = getattr(mod, setting)

                if setting in self._default_settings:
                    self._default_settings[setting].check_type(setting_value)

                setattr(self, setting, setting_value)
                self._explicit_settings.add(setting)

        if hasattr(time, "tzset") and self.TIME_ZONE:
            # When we can, attempt to validate the timezone. If we can't find
            # this file, no check happens and it's harmless.
            zoneinfo_root = Path("/usr/share/zoneinfo")
            zone_info_file = zoneinfo_root.joinpath(*self.TIME_ZONE.split("/"))
            if zoneinfo_root.exists() and not zone_info_file.exists():
                raise ValueError("Incorrect timezone setting: %s" % self.TIME_ZONE)
            # Move the time zone info into os.environ. See ticket #2315 for why
            # we don't do this unconditionally (breaks Windows).
            os.environ["TZ"] = self.TIME_ZONE
            time.tzset()

    def _load_module_settings(self, module):
        annotations = getattr(module, "__annotations__", {})

        for setting in dir(module):
            if setting.isupper():
                if hasattr(self, setting):
                    raise ImproperlyConfigured("The %s setting is duplicated" % setting)

                setting_value = getattr(module, setting)

                # Set a simple attr on the settings object
                setattr(self, setting, setting_value)

                # Store a more complex setting reference for more detail
                self._default_settings[setting] = DefaultSetting(
                    name=setting,
                    value=setting_value,
                    annotation=annotations.get(setting, ""),
                    module=module,
                )

    def is_overridden(self, setting):
        return setting in self._explicit_settings

    def __repr__(self):
        return '<{cls} "{settings_module}">'.format(
            cls=self.__class__.__name__,
            settings_module=self.SETTINGS_MODULE,
        )


# Currently used for test settings override... nothing else
class UserSettingsHolder:
    """Holder for user configured settings."""

    # SETTINGS_MODULE doesn't make much sense in the manually configured
    # (standalone) case.
    SETTINGS_MODULE = None

    def __init__(self, default_settings):
        """
        Requests for configuration variables not in this class are satisfied
        from the module specified in default_settings (if possible).
        """
        self.__dict__["_deleted"] = set()
        self.default_settings = default_settings

    def __getattr__(self, name):
        if not name.isupper() or name in self._deleted:
            raise AttributeError
        return getattr(self.default_settings, name)

    def __setattr__(self, name, value):
        self._deleted.discard(name)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        self._deleted.add(name)
        if hasattr(self, name):
            super().__delattr__(name)

    def __dir__(self):
        return sorted(
            s
            for s in [*self.__dict__, *dir(self.default_settings)]
            if s not in self._deleted
        )

    def is_overridden(self, setting):
        deleted = setting in self._deleted
        set_locally = setting in self.__dict__
        set_on_default = getattr(
            self.default_settings, "is_overridden", lambda s: False
        )(setting)
        return deleted or set_locally or set_on_default

    def __repr__(self):
        return "<{cls}>".format(
            cls=self.__class__.__name__,
        )
