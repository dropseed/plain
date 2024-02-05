import importlib
import json
import os
import time
import types
import typing
from importlib.util import find_spec
from pathlib import Path

from plain.exceptions import ImproperlyConfigured
from plain.packages import PackageConfig

ENVIRONMENT_VARIABLE = "PLAIN_SETTINGS_MODULE"
ENV_SETTINGS_PREFIX = "PLAIN_"
CUSTOM_SETTINGS_PREFIX = "APP_"


class Settings:
    """
    Settings and configuration for Plain.

    This class handles loading settings from the module specified by the
    PLAIN_SETTINGS_MODULE environment variable, as well as from default settings,
    environment variables, and explicit settings in the settings module.

    Lazy initialization is implemented to defer loading until settings are first accessed.
    """

    def __init__(self, settings_module=None):
        self._settings_module = settings_module
        self._settings = {}
        self._errors = []  # Collect configuration errors
        self.configured = False

    def _setup(self):
        if self.configured:
            return
        else:
            self.configured = True

        self._settings = {}  # Maps setting names to SettingDefinition instances

        # Determine the settings module
        if self._settings_module is None:
            self._settings_module = os.environ.get(ENVIRONMENT_VARIABLE, "app.settings")

        # First load the global settings from plain
        self._load_module_settings(
            importlib.import_module("plain.runtime.global_settings")
        )

        # Import the user's settings module
        try:
            mod = importlib.import_module(self._settings_module)
        except ImportError as e:
            raise ImproperlyConfigured(
                f"Could not import settings '{self._settings_module}': {e}"
            )

        # Keep a reference to the settings.py module path
        self.path = Path(mod.__file__).resolve()

        # Load default settings from installed packages
        self._load_default_settings(mod)
        # Load environment settings
        self._load_env_settings()
        # Load explicit settings from the settings module
        self._load_explicit_settings(mod)
        # Check for any required settings that are missing
        self._check_required_settings()
        # Check for any collected errors
        self._raise_errors_if_any()

    def _load_module_settings(self, module):
        annotations = getattr(module, "__annotations__", {})
        settings = dir(module)

        for setting in settings:
            if setting.isupper():
                if setting in self._settings:
                    self._errors.append(f"Duplicate setting '{setting}'.")
                    continue

                setting_value = getattr(module, setting)
                self._settings[setting] = SettingDefinition(
                    name=setting,
                    default_value=setting_value,
                    annotation=annotations.get(setting, None),
                    module=module,
                )

        # Store any annotations that didn't have a value (these are required settings)
        for setting, annotation in annotations.items():
            if setting not in self._settings:
                self._settings[setting] = SettingDefinition(
                    name=setting,
                    default_value=None,
                    annotation=annotation,
                    module=module,
                    required=True,
                )

    def _load_default_settings(self, settings_module):
        for entry in getattr(settings_module, "INSTALLED_PACKAGES", []):
            if isinstance(entry, PackageConfig):
                app_settings = entry.module.default_settings
            elif find_spec(f"{entry}.default_settings"):
                app_settings = importlib.import_module(f"{entry}.default_settings")
            else:
                continue

            self._load_module_settings(app_settings)

    def _load_env_settings(self):
        env_settings = {
            k[len(ENV_SETTINGS_PREFIX) :]: v
            for k, v in os.environ.items()
            if k.startswith(ENV_SETTINGS_PREFIX) and k.isupper()
        }
        for setting, value in env_settings.items():
            if setting in self._settings:
                setting_def = self._settings[setting]
                try:
                    parsed_value = _parse_env_value(value, setting_def.annotation)
                    setting_def.set_value(parsed_value, "env")
                except ImproperlyConfigured as e:
                    self._errors.append(str(e))

    def _load_explicit_settings(self, settings_module):
        for setting in dir(settings_module):
            if setting.isupper():
                setting_value = getattr(settings_module, setting)

                if setting in self._settings:
                    setting_def = self._settings[setting]
                    try:
                        setting_def.set_value(setting_value, "explicit")
                    except ImproperlyConfigured as e:
                        self._errors.append(str(e))
                        continue

                elif setting.startswith(CUSTOM_SETTINGS_PREFIX):
                    # Accept custom settings prefixed with '{CUSTOM_SETTINGS_PREFIX}'
                    setting_def = SettingDefinition(
                        name=setting,
                        default_value=None,
                        annotation=None,
                        required=False,
                    )
                    try:
                        setting_def.set_value(setting_value, "explicit")
                    except ImproperlyConfigured as e:
                        self._errors.append(str(e))
                        continue
                    self._settings[setting] = setting_def
                else:
                    # Collect unrecognized settings individually
                    self._errors.append(
                        f"Unknown setting '{setting}'. Custom settings must start with '{CUSTOM_SETTINGS_PREFIX}'."
                    )

        if hasattr(time, "tzset") and self.TIME_ZONE:
            zoneinfo_root = Path("/usr/share/zoneinfo")
            zone_info_file = zoneinfo_root.joinpath(*self.TIME_ZONE.split("/"))
            if zoneinfo_root.exists() and not zone_info_file.exists():
                self._errors.append(
                    f"Invalid TIME_ZONE setting '{self.TIME_ZONE}'. Timezone file not found."
                )
            else:
                os.environ["TZ"] = self.TIME_ZONE
                time.tzset()

    def _check_required_settings(self):
        missing = [k for k, v in self._settings.items() if v.required and not v.is_set]
        if missing:
            self._errors.append(f"Missing required setting(s): {', '.join(missing)}.")

    def _raise_errors_if_any(self):
        if self._errors:
            errors = ["- " + e for e in self._errors]
            raise ImproperlyConfigured(
                "Settings configuration errors:\n" + "\n".join(errors)
            )

    def __getattr__(self, name):
        # Avoid recursion by directly returning internal attributes
        if not name.isupper():
            return object.__getattribute__(self, name)

        self._setup()

        if name in self._settings:
            return self._settings[name].value
        else:
            raise AttributeError(f"'Settings' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        # Handle internal attributes without recursion
        if not name.isupper():
            object.__setattr__(self, name, value)
        else:
            if name in self._settings:
                self._settings[name].set_value(value, "runtime")
                self._raise_errors_if_any()
            else:
                object.__setattr__(self, name, value)

    def __repr__(self):
        if not self.configured:
            return "<Settings [Unevaluated]>"
        return f'<Settings "{self._settings_module}">'


def _parse_env_value(value, annotation):
    if not annotation:
        raise ImproperlyConfigured("Type hint required to set from environment.")

    if annotation is bool:
        # Special case for bools
        return value.lower() in ("true", "1", "yes")
    elif annotation is str:
        return value
    else:
        # Parse other types using JSON
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ImproperlyConfigured(
                f"Invalid JSON value for setting: {e.msg}"
            ) from e


class SettingDefinition:
    """Store detailed information about settings."""

    def __init__(
        self, name, default_value=None, annotation=None, module=None, required=False
    ):
        self.name = name
        self.default_value = default_value
        self.annotation = annotation
        self.module = module
        self.required = required
        self.value = default_value
        self.source = "default"  # 'default', 'env', 'explicit', or 'runtime'
        self.is_set = False  # Indicates if the value was set explicitly

    def set_value(self, value, source):
        self.check_type(value)
        self.value = value
        self.source = source
        self.is_set = True

    def check_type(self, obj):
        if not self.annotation:
            return

        if not SettingDefinition._is_instance_of_type(obj, self.annotation):
            raise ImproperlyConfigured(
                f"'{self.name}': Expected type {self.annotation}, but got {type(obj)}."
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
                SettingDefinition._is_instance_of_type(value, arg)
                for arg in typing.get_args(type_hint)
            )

        # List types
        if typing.get_origin(type_hint) is list:
            return isinstance(value, list) and all(
                SettingDefinition._is_instance_of_type(
                    item, typing.get_args(type_hint)[0]
                )
                for item in value
            )

        # Tuple types
        if typing.get_origin(type_hint) is tuple:
            return isinstance(value, tuple) and all(
                SettingDefinition._is_instance_of_type(
                    item, typing.get_args(type_hint)[i]
                )
                for i, item in enumerate(value)
            )

        raise ValueError(f"Unsupported type hint: {type_hint}")

    def __str__(self):
        return f"SettingDefinition(name={self.name}, value={self.value}, source={self.source})"
