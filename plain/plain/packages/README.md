# Packages

Create app-packages and install third-party packages from PyPI.

Like Django, Plain is heavily dependent on the concept of "packages".

In your `settings.py`, you define which packages are enabled with the `INSTALLED_PACKAGES` setting.

```python
# app/settings.py
INSTALLED_PACKAGES = [

]
```

These can refer to third-party packages from PyPI (after you've installed them with `pip`),
or they can refer to packages that you've written yourself.

- some packages don't need to be installed as packages, but most do (and should specify)


## Your own packages

- naming examples
- startapp


## App settings

```python
# <app>/default_settings.py
EXAMPLE_SETTING: str = "example"
```

```python
# <app>/models.py
from plain.runtime import settings


print(settings.EXAMPLE_SETTING)
```
