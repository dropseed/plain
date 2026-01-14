from __future__ import annotations

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
from plain.runtime.secret import Secret

_ENVIRONMENT_VARIABLE = "PLAIN_SETTINGS_MODULE"
_DEFAULT_ENV_SETTINGS_PREFIXES = ["PLAIN_"]
_CUSTOM_SETTINGS_PREFIX = "APP_"


class Settings:
    """
    Settings and configuration for Plain.

    This class handles loading settings from the module specified by the
    PLAIN_SETTINGS_MODULE environment variable, as well as from default settings,
    environment variables, and explicit settings in the settings module.

    Lazy initialization is implemented to defer loading until settings are first accessed.
    """

    def __init__(self, settings_module: str | None = None):
        self._settings_module = settings_module
        self._settings: dict[str, SettingDefinition] = {}
        self._errors: list[str] = []  # Collect configuration errors
        self._env_prefixes: list[str] = []  # Configured env prefixes
        self.configured = False

    def _setup(self) -> None:
        if self.configured:
            return
        else:
            self.configured = True

        self._settings = {}  # Maps setting names to SettingDefinition instances

        # Determine the settings module
        if self._settings_module is None:
            self._settings_module = os.environ.get(
                _ENVIRONMENT_VARIABLE, "app.settings"
            )

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
        assert mod.__file__ is not None
        self.path = Path(mod.__file__).resolve()

        # Get env prefixes from settings module (must be configured in settings.py, not env)
        self._env_prefixes = getattr(
            mod, "ENV_SETTINGS_PREFIXES", _DEFAULT_ENV_SETTINGS_PREFIXES
        )

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

    def _load_module_settings(self, module: types.ModuleType) -> None:
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

    def _load_default_settings(self, settings_module: types.ModuleType) -> None:
        for entry in getattr(settings_module, "INSTALLED_PACKAGES", []):
            if isinstance(entry, PackageConfig):
                app_settings = entry.module.default_settings
            elif find_spec(f"{entry}.default_settings"):
                app_settings = importlib.import_module(f"{entry}.default_settings")
            else:
                continue

            self._load_module_settings(app_settings)

    def _load_env_settings(self) -> None:
        # Collect env settings from all configured prefixes
        # First prefix wins if same setting appears with multiple prefixes
        env_settings: dict[
            str, tuple[str, str]
        ] = {}  # setting_name -> (value, env_var)
        for prefix in self._env_prefixes:
            for key, value in os.environ.items():
                if key.startswith(prefix) and key.isupper():
                    setting_name = key[len(prefix) :]
                    if setting_name and setting_name not in env_settings:
                        env_settings[setting_name] = (value, key)

        for setting, (value, env_var) in env_settings.items():
            if setting in self._settings:
                setting_def = self._settings[setting]
                try:
                    parsed_value = _parse_env_value(
                        value, setting_def.annotation, setting
                    )
                    setting_def.set_value(parsed_value, "env")
                    setting_def.env_var_name = env_var
                except ImproperlyConfigured as e:
                    self._errors.append(str(e))

    def _load_explicit_settings(self, settings_module: types.ModuleType) -> None:
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

                elif setting.startswith(_CUSTOM_SETTINGS_PREFIX):
                    # Accept custom settings prefixed with '{_CUSTOM_SETTINGS_PREFIX}'
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
                        f"Unknown setting '{setting}'. Custom settings must start with '{_CUSTOM_SETTINGS_PREFIX}'."
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

    def _check_required_settings(self) -> None:
        missing = [k for k, v in self._settings.items() if v.required and not v.is_set]
        if missing:
            self._errors.append(f"Missing required setting(s): {', '.join(missing)}.")

    def _raise_errors_if_any(self) -> None:
        if self._errors:
            errors = ["- " + e for e in self._errors]
            raise ImproperlyConfigured(
                "Settings configuration errors:\n" + "\n".join(errors)
            )

    def __getattr__(self, name: str) -> typing.Any:
        # Avoid recursion by directly returning internal attributes
        if not name.isupper():
            return object.__getattribute__(self, name)

        self._setup()

        if name in self._settings:
            return self._settings[name].value
        else:
            raise AttributeError(f"'Settings' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: typing.Any) -> None:
        # Handle internal attributes without recursion
        if not name.isupper():
            object.__setattr__(self, name, value)
        else:
            if name in self._settings:
                self._settings[name].set_value(value, "runtime")
                self._raise_errors_if_any()
            else:
                object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        if not self.configured:
            return "<Settings [Unevaluated]>"
        return f'<Settings "{self._settings_module}">'

    def get_settings(
        self, *, source: str | None = None
    ) -> list[tuple[str, SettingDefinition]]:
        """
        Get settings as a sorted list of (name, definition) tuples.

        Args:
            source: Filter to settings from a specific source ('default', 'env', 'explicit', 'runtime')
        """
        self._setup()
        result = []
        for name, defn in sorted(self._settings.items()):
            if source is not None and defn.source != source:
                continue
            result.append((name, defn))
        return result

    def get_env_settings(self) -> list[tuple[str, SettingDefinition]]:
        """Get settings that were loaded from environment variables."""
        return self.get_settings(source="env")


def _parse_env_value(
    value: str, annotation: type | None, setting_name: str
) -> typing.Any:
    if not annotation:
        raise ImproperlyConfigured(
            f"{setting_name}: Type hint required to set from environment."
        )

    # Unwrap Secret[T] to get the inner type
    if typing.get_origin(annotation) is Secret:
        if args := typing.get_args(annotation):
            annotation = args[0]

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
                f"Invalid JSON value for setting '{setting_name}': {e.msg}"
            ) from e


class SettingDefinition:
    """Store detailed information about settings."""

    def __init__(
        self,
        name: str,
        default_value: typing.Any = None,
        annotation: type | None = None,
        module: types.ModuleType | None = None,
        required: bool = False,
    ):
        self.name = name
        self.default_value = default_value
        self.annotation = annotation
        self.module = module
        self.required = required
        self.value = default_value
        self.source = "default"  # 'default', 'env', 'explicit', or 'runtime'
        self.is_set = False  # Indicates if the value was set explicitly
        self.env_var_name: str | None = None  # Env var name if loaded from env
        self.is_secret = self._check_if_secret(annotation)

    @staticmethod
    def _check_if_secret(annotation: type | None) -> bool:
        """Check if annotation is Secret[T]."""
        return annotation is not None and typing.get_origin(annotation) is Secret

    def display_value(self) -> str:
        """Return value for display, masked if secret."""
        if self.is_secret:
            return "********"
        return repr(self.value)

    def set_value(self, value: typing.Any, source: str) -> None:
        self.check_type(value)
        self.value = value
        self.source = source
        self.is_set = True

    def check_type(self, obj: typing.Any) -> None:
        if not self.annotation:
            return

        if not SettingDefinition._is_instance_of_type(obj, self.annotation):
            raise ImproperlyConfigured(
                f"'{self.name}': Expected type {self.annotation}, but got {type(obj)}."
            )

    @staticmethod
    def _is_instance_of_type(value: typing.Any, type_hint: typing.Any) -> bool:
        # Simple types
        if isinstance(type_hint, type):
            return isinstance(value, type_hint)

        origin = typing.get_origin(type_hint)

        # Secret[T] - check the inner type (Secret is just a marker)
        if origin is Secret:
            args = typing.get_args(type_hint)
            if args:
                return SettingDefinition._is_instance_of_type(value, args[0])
            return True

        # Union types
        if origin is typing.Union or origin is types.UnionType:
            return any(
                SettingDefinition._is_instance_of_type(value, arg)
                for arg in typing.get_args(type_hint)
            )

        # List types
        if origin is list:
            return isinstance(value, list) and all(
                SettingDefinition._is_instance_of_type(
                    item, typing.get_args(type_hint)[0]
                )
                for item in value
            )

        # Tuple types
        if origin is tuple:
            return isinstance(value, tuple) and all(
                SettingDefinition._is_instance_of_type(
                    item, typing.get_args(type_hint)[i]
                )
                for i, item in enumerate(value)
            )

        raise ValueError(f"Unsupported type hint: {type_hint}")

    def __str__(self) -> str:
        return f"SettingDefinition(name={self.name}, value={self.value}, source={self.source})"
