# plain.tailwind

**Integrate Tailwind CSS without JavaScript or npm.**

- [Overview](#overview)
- [CLI commands](#cli-commands)
    - [`plain tailwind init`](#plain-tailwind-init)
    - [`plain tailwind build`](#plain-tailwind-build)
    - [`plain tailwind update`](#plain-tailwind-update)
- [Template tag](#template-tag)
- [Settings](#settings)
- [Adding custom CSS](#adding-custom-css)
- [Deployment](#deployment)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use Tailwind CSS in your Plain project without Node.js or npm. This package automatically downloads and manages the [Tailwind standalone CLI](https://tailwindcss.com/blog/standalone-cli) for you.

Initialize Tailwind in your project:

```sh
plain tailwind init
```

This creates a `tailwind.css` source file in your project root. Then compile your CSS:

```sh
plain tailwind build
```

For development, use watch mode to automatically recompile when files change:

```sh
plain tailwind build --watch
```

Include the compiled CSS in your templates:

```html
<!DOCTYPE html>
<html>
<head>
    {% tailwind_css %}
</head>
<body>
    <h1 class="text-3xl font-bold text-blue-600">Hello, Tailwind!</h1>
</body>
</html>
```

## CLI commands

### `plain tailwind init`

Sets up Tailwind in your project. This command:

1. Downloads the Tailwind standalone CLI (if not already installed)
2. Creates a `tailwind.css` source file in your project root

```sh
plain tailwind init
```

### `plain tailwind build`

Compiles your Tailwind CSS from the source file to `app/assets/tailwind.min.css`.

```sh
# One-time build
plain tailwind build

# Watch mode for development
plain tailwind build --watch

# Minified build for production
plain tailwind build --minify
```

The build command automatically installs or updates the Tailwind CLI if needed.

### `plain tailwind update`

Updates to the latest version of Tailwind CSS:

```sh
plain tailwind update
```

This downloads the newest version and updates your `pyproject.toml`.

## Template tag

The `tailwind_css` template tag includes the compiled CSS file in your templates. Place it in your base template's `<head>`:

```html
<!DOCTYPE html>
<html>
<head>
    {% tailwind_css %}
</head>
<body>
    {% block content %}{% endblock %}
</body>
</html>
```

The tag renders a `<link>` element pointing to your compiled CSS file.

## Settings

| Setting              | Default                       | Env var |
| -------------------- | ----------------------------- | ------- |
| `TAILWIND_SRC_PATH`  | `<project>/tailwind.css`      | -       |
| `TAILWIND_DIST_PATH` | `app/assets/tailwind.min.css` | -       |

See [`default_settings.py`](./default_settings.py) for more details.

The Tailwind version is tracked in your `pyproject.toml`:

```toml
[tool.plain.tailwind]
version = "4.0.0"
```

When you run `plain tailwind build`, it automatically checks if your local installation matches this version and updates if needed.

## Adding custom CSS

Add custom CSS to your source file (by default `tailwind.css` at the project root):

```css
@import "tailwindcss";
@import "./.plain/tailwind.css";

/* Add your custom styles here */
.btn-primary {
    @apply bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded;
}

.custom-gradient {
    background: linear-gradient(to right, #4f46e5, #7c3aed);
}
```

The `@import "./.plain/tailwind.css"` line includes styles from all your installed Plain packages.

[Read the Tailwind docs for more about using custom styles.](https://tailwindcss.com/docs/adding-custom-styles)

## Deployment

For production deployments:

1. Add `app/assets/tailwind.min.css` to your `.gitignore`
2. Run `plain tailwind build --minify` as part of your deployment process

The build command automatically installs the Tailwind CLI if it is not present, making deployments seamless.

You can automate this by adding a build command to your `pyproject.toml`:

```toml
[tool.plain.build.run]
tailwind = {cmd = "plain tailwind build --minify"}
```

## FAQs

#### How does this work without Node.js?

Tailwind provides a [standalone CLI](https://tailwindcss.com/blog/standalone-cli) that bundles everything needed to compile CSS. This package downloads the appropriate binary for your platform (macOS, Linux, or Windows) and manages it for you.

#### Where is the Tailwind CLI stored?

The Tailwind binary and version information are stored in a `.plain` directory in your project root. Add this to your `.gitignore`:

```
.plain/
```

#### How do I use Tailwind classes from other Plain packages?

The `@import "./.plain/tailwind.css"` line in your source CSS automatically includes `@source` directives for all installed Plain packages. This ensures Tailwind scans those packages for class usage.

#### Can I use Tailwind plugins?

The standalone CLI includes all first-party plugins. For third-party plugins that require npm, you would need to use the standard Tailwind installation instead.

## Installation

Install the `plain.tailwind` package from [PyPI](https://pypi.org/project/plain.tailwind/):

```sh
uv add plain.tailwind
```

Add `plain.tailwind` to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.tailwind",
]
```

Add `.plain/` to your `.gitignore`:

```
.plain/
```

Initialize Tailwind in your project:

```sh
plain tailwind init
```

Add the `tailwind_css` template tag to your base template:

```html
<!DOCTYPE html>
<html>
<head>
    {% tailwind_css %}
</head>
<body>
    {% block content %}{% endblock %}
</body>
</html>
```

Run the build command to compile your CSS:

```sh
plain tailwind build --watch
```
