# django-importmap

## Input

```toml
[[packages]]
name = "react"
source = "react@17.0.2"
```

```html
{% load static importmap %}
<!DOCTYPE html>
<html lang="en">
<head>
    {% importmap_scripts %}
    <script type="module" src="{% static 'app.js' %}"></script>
</head>
<body>

</body>
</html>
```

```js
import React from "react"

console.log(React);
```

## Output

```sh
python manage.py importmap_generate
```

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

    <script type="module" src="/static/app.js"></script>
</head>
<body>

</body>
</html>
```

## Project status

To do:

- Automatically rebuild importmap.lock during runserver / on config modification
- Django check for comparing lock and config (at deploy time, etc.)
- Use deps to update shim version
- Preload option
- Vendoring option
- Command to add new importmap dependency? (use `^` version automatically?)
- More complete error handling
