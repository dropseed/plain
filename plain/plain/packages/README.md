# Packages

**Register and configure Python modules as Plain packages.**

- [Overview](#overview)
- [Creating app packages](#creating-app-packages)
- [Package settings](#package-settings)
- [Package configuration](#package-configuration)
    - [The `ready()` method](#the-ready-method)
    - [Custom package labels](#custom-package-labels)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Most Python modules you use with Plain need to be listed in `settings.INSTALLED_PACKAGES`. This enables template detection, per-package settings, database models, and other features.

```python
# app/settings.py
INSTALLED_PACKAGES = [
    "plain.models",
    "plain.tailwind",
    "plain.auth",
    "plain.passwords",
    "plain.sessions",
    "plain.htmx",
    "plain.admin",
    "plain.elements",
    # Local packages
    "app.users",
    "app.teams",
]
```

A package can be a third-party module from PyPI or a local module inside your `app` directory.

## Creating app packages

You can split your app into multiple local packages. For example, instead of a single `core` package containing everything, you might have separate `users`, `teams`, and `projects` packages. If you find yourself creating a package with a generic name like `core` or `base`, consider splitting it up.

Create a new package by running:

```bash
plain create <package_name>
```

Make sure to add it to `settings.INSTALLED_PACKAGES` if it uses templates, models, or other Plain-specific features.

## Package settings

An installed package can define its own settings. These could be default values for how the package behaves, or required settings that must be configured by the user.

Create a `default_settings.py` file in your package:

```python
# teams/default_settings.py

# A default setting (has a value)
TEAMS_MAX_MEMBERS: int = 10

# A required setting (type annotation with no default value)
TEAMS_SIGNUP_ENABLED: bool
```

Access settings at runtime through the `settings` object:

```python
# teams/views.py
from plain.runtime import settings


def team_view(request):
    if settings.TEAMS_SIGNUP_ENABLED:
        max_members = settings.TEAMS_MAX_MEMBERS
        # ...
```

Namespace your settings to avoid conflicts. If your package is named `teams`, prefix all settings with `TEAMS_`.

## Package configuration

To customize how your package loads or run setup code when Plain starts, create a [`PackageConfig`](./config.py#PackageConfig) subclass in a `config.py` file:

```python
# teams/config.py
from plain.packages import PackageConfig, register_config


@register_config
class TeamsConfig(PackageConfig):
    pass
```

The [`@register_config`](./registry.py#register_config) decorator registers your configuration with the [`packages_registry`](./registry.py#packages_registry).

### The `ready()` method

Override the `ready()` method to run code when Plain starts. This is useful for connecting signals, initializing caches, or other one-time setup.

```python
# teams/config.py
from plain.packages import PackageConfig, register_config


@register_config
class TeamsConfig(PackageConfig):
    def ready(self):
        # Import signal handlers
        from . import signals  # noqa: F401
        print("Teams package ready!")
```

### Custom package labels

By default, the package label is the last component of the Python path (e.g., `admin` for `plain.admin`). You can override this by setting the `package_label` attribute:

```python
# teams/config.py
from plain.packages import PackageConfig, register_config


@register_config
class TeamsConfig(PackageConfig):
    package_label = "teams"
```

## FAQs

#### When do I need a `config.py` file?

You only need a `config.py` file if you want to run code in `ready()` or customize the package label. For most packages, Plain automatically creates a default configuration.

#### How do I access the package registry?

You can access the registry directly if you need to inspect installed packages:

```python
from plain.packages import packages_registry

# Get all registered package configs
for config in packages_registry.get_package_configs():
    print(config.name, config.path)

# Get a specific package config by label
teams_config = packages_registry.get_package_config("teams")
```

See [`PackagesRegistry`](./registry.py#PackagesRegistry) for all available methods.

#### What order are packages loaded?

Packages are loaded in the order they appear in `INSTALLED_PACKAGES`. The `ready()` methods are called in the same order after all packages have been imported.

#### Can I have duplicate package labels?

No. Each package must have a unique label. If two packages have the same label, Plain raises an `ImproperlyConfigured` error.

## Installation

The `plain.packages` module is included with the `plain` package. No additional installation is required.

```bash
uv add plain
```
