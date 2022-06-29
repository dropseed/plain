# forge-format

A unified, opinionated code formatting command for Django projects.

Uses [black](https://github.com/psf/black) and [isort](https://pycqa.github.io/isort/) to format Python code.


## Installation

### Forge installation

The `forge-format` package is a dependency of [`forge`](https://github.com/forgepackages/forge) and is available as `forge format`.

If you use the [Forge quickstart](https://www.forgepackages.com/docs/quickstart/),
everything you need will already be set up.

The [standard Django installation](#standard-django-installation) can give you an idea of the steps involved.


### Standard Django installation

This package can be used without `forge` by installing it as a regular Django app.

First, install `forge-format` from [PyPI](https://pypi.org/project/forge-format/):

```sh
pip install forge-format
```

Then add it to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    "forgeformat",
]
```

Now you will have access to the `format` command:

```sh
python manage.py format
```
