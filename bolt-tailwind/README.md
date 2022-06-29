# forge-tailwind

Use [Tailwind CSS](https://tailwindcss.com/) with [Django](https://www.djangoproject.com/) *without* requiring npm.

Made possible by the [Tailwind standalone CLI](https://tailwindcss.com/blog/standalone-cli).

## Installation

### Forge installation

The `forge-tailwind` package is a dependency of [`forge`](https://github.com/forgepackages/forge) and is available as `forge tailwind`.

If you use the [Forge quickstart](https://www.forgepackages.com/docs/quickstart/),
everything you need will already be set up.

The [standard Django installation](#standard-django-installation) can give you an idea of the steps involved.


### Standard Django installation

This package can be used without `forge` by installing it as a regular Django app.

First, install `forge-tailwind` from [PyPI](https://pypi.org/project/forge-tailwind/):

```sh
pip install forge-tailwind
```

Then add it to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    "forgetailwind",
]
```

Create a new `tailwind.config.js` file in your project root:

```sh
python manage.py tailwind init
```

This will also create a `tailwind.css` file at `static/src/tailwind.css` where additional CSS can be added.
You can customize where these files are located if you need to,
but this is the default (requires `STATICFILES_DIRS = [BASE_DIR / "static"]`).

The `src/tailwind.css` file is then compiled into `dist/tailwind.css` by running `tailwind compile`:

```sh
python manage.py tailwind compile
```

When you're working locally, add `--watch` to automatically compile as changes are made:

```sh
python manage.py tailwind compile --watch
```

Then include the compiled CSS in your base template `<head>`:

```html
<link rel="stylesheet" href="{% static 'dist/tailwind.css' %}">
```

In your repo you will notice a new `.forge` directory that contains `tailwind` (the standalone CLI binary) and `tailwind.version` (to track the version currently installed).
You should add `.forge` to your `.gitignore` file.

## Updating Tailwind

This package manages the Tailwind versioning by comparing `.forge/tailwind.version` to the `FORGE_TAILWIND_VERSION` variable that is injected into your `tailwind.config.js` file.
When you run `tailwind compile`,
it will automatically check whether your local installation needs to be updated and will update it if necessary.

You can use the `update` command to update your project to the latest version of Tailwind:

```sh
tailwind update
```

## Deployment

If possible, you should add `static/dist/tailwind.css` to your `.gitignore` and run the `tailwind compile --minify` command as a part of your deployment pipeline.

When you run `tailwind compile`, it will automatically check whether the Tailwind standalone CLI has been installed, and install it if it isn't.

When using Forge on Heroku, we do this for you automatically in our [Forge buildpack](https://github.com/forgepackages/heroku-buildpack-forge/blob/master/bin/files/post_compile).
