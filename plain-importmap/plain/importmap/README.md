# plain.importmap

Use import maps in templates.

Heavily inspired by [rails/importmap-rails](https://github.com/rails/importmap-rails),
this app adds a simple process for integrating [import maps](https://github.com/WICG/import-maps) into Django.

This is a new project and it hasn't been used in production yet.
But if you're looking to use import maps with Django, give it a try and tell us how it goes.
The structure (and code) is pretty simple.
Contributions are welcome!

## How to use it

You'll need to do four things to use plain-importmap.

The TL;DR is:

- Add "importmap" to `INSTALLED_PACKAGES`
- Create an `importmap.toml`
- Run `python manage.py importmap_generate`
- Use `{% importmap_js %}` in your template

### 1. Install it

Do the equivalent of `pip install plain-importmap` and add it to your `INSTALLED_PACKAGES` list in your `settings.py` file.

```python
# settings.py
INSTALLED_PACKAGES = [
    ...
    "importmap",
]
```

### 2. Create an `importmap.toml` file

This should live next to your `manage.py` file.
Here you'll add a list of "packages" you want to use.

The "name" can be anything, but should probably be the same as what it you would import from in typical bundling setups (i.e. `import React from "react"`).

The "source" will get passed on to the [jspm.org generator](https://jspm.org/docs/api#install), but is basically the `<npm package>@<version>` you want to use.

```toml
[[packages]]
name = "react"
source = "react@17.0.2"
```

### 3. Run `importmap_generate`

To resolve the import map, you'll need to run `python manage.py importmap_generate`.

This will create `importmap.lock` (which you should save and commit to your repo) that contains the actual import map JSON (both for development and production).

You don't need to look at this file yourself, but here is an example of what it will contain:

```json
{
  "config_hash": "09d6237cdd891aad07de60f54689d130",
  "importmap": {
    "imports": {
      "react": "https://ga.jspm.io/npm:react@17.0.2/index.js"
    },
    "scopes": {
      "https://ga.jspm.io/": {
        "object-assign": "https://ga.jspm.io/npm:object-assign@4.1.1/index.js"
      }
    }
  },
  "importmap_dev": {
    "imports": {
      "react": "https://ga.jspm.io/npm:react@17.0.2/dev.index.js"
    },
    "scopes": {
      "https://ga.jspm.io/": {
        "object-assign": "https://ga.jspm.io/npm:object-assign@4.1.1/index.js"
      }
    }
  }
}
```

### 4. Add the scripts to your template

The import map itself gets added by using `{% load importmap %}` and then `{% importmap_js %}` in the head of your HTML. This will include the [es-module-shim](https://github.com/guybedford/es-module-shims).

After that, you can include your own JavaScript!
This could be inline or from `static`.
Just be sure to use `type="module"` and the "name" you provided when doing your JS imports (i.e. "react").

```html
{% load importmap %}
<!DOCTYPE html>
<html lang="en">
<head>
    {% importmap_js %}
    <script type="module">
        import React from "react"

        console.log(React);
    </script>
</head>
<body>

</body>
</html>
```

When it renders you should get something like this:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <script async src="https://ga.jspm.io/npm:es-module-shims@1.3.6/dist/es-module-shims.js"></script>
    <script type="importmap">
    {
        "imports": {
            "react": "https://ga.jspm.io/npm:react@17.0.2/dev.index.js"
        },
        "scopes": {
            "https://ga.jspm.io/": {
                "object-assign": "https://ga.jspm.io/npm:object-assign@4.1.1/index.js"
            }
        }
    }
    </script>

    <script type="module">
        import React from "react"

        console.log(React);
    </script>
</head>
<body>

</body>
</html>
```

## Project status

This is partly an experiment,
but honestly it's so simple that I don't think there can be much wrong with how it works currently.

Here's a list of things that would be nice to do (PRs welcome):

- Command to add new importmap dependency (use `^` version automatically?)
- Django check for comparing lock and config (at deploy time, etc.)
- Use [deps](https://www.dependencies.io/) to update shim version
- Preload option
- Vendoring option (including shim)
- More complete error handling (custom exceptions, etc.)
