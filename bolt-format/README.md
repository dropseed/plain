A unified, opinionated code formatting command for Django projects.

Uses [black](https://github.com/psf/black) and [isort](https://pycqa.github.io/isort/) to format Python code.


## Installation

### Django + Forge Quickstart

If you use the [Forge Quickstart](https://www.forgepackages.com/docs/forge/quickstart/),
everything you need will be ready and available as `forge format`.

### Install for existing Django projects

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
