# Apps

Like Django, Bolt is heavily dependent on the concept of "apps".

In your `settings.py`, you define which apps are enabled with the `INSTALLED_APPS` setting.

```python
# app/settings.py
INSTALLED_APPS = [

]
```

These can refer to third-party packages from PyPI (after you've installed them with `pip`),
or they can refer to apps that you've written yourself.

- some packages don't need to be installed as apps, but most do (and should specify)


## Your own apps

- naming examples
- startapp


## App settings

```python
# <app>/default_settings.py
EXAMPLE_SETTING: str = "example"
```

```python
# <app>/models.py
from bolt.runtime import settings


print(settings.EXAMPLE_SETTING)
```
