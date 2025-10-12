# plain.tailwind

**Integrate Tailwind CSS without JavaScript or npm.**

- [Overview](#overview)
- [Basic Usage](#basic-usage)
    - [Commands](#commands)
    - [Template Tag](#template-tag)
- [Configuration](#configuration)
    - [Updating Tailwind](#updating-tailwind)
    - [Adding Custom CSS](#adding-custom-css)
- [Deployment](#deployment)
- [Installation](#installation)

## Overview

This package allows you to use Tailwind CSS in your Plain project without requiring Node.js or npm. It uses the [Tailwind standalone CLI](https://tailwindcss.com/blog/standalone-cli), which is automatically downloaded and managed for you.

First, initialize Tailwind in your project:

```sh
plain tailwind init
```

This creates a `tailwind.config.js` file in your project root and a source CSS file.

Then compile your CSS:

```sh
plain tailwind build
```

For development, use watch mode to automatically recompile when files change:

```sh
plain tailwind build --watch
```

Include the compiled CSS in your templates:

```html
{% tailwind_css %}
```

## Basic Usage

### Commands

The `plain tailwind` command provides several subcommands:

```console
$ plain tailwind
Usage: plain tailwind [OPTIONS] COMMAND [ARGS]...

  Tailwind CSS

Options:
  --help  Show this message and exit.

Commands:
  build    Compile a Tailwind CSS file
  init     Install Tailwind and create tailwind.css
  install  Install the Tailwind standalone CLI
  update   Update the Tailwind CSS version
```

- `init` - Sets up Tailwind in your project, creating necessary config files
- `build` - Compiles your Tailwind CSS (use `--watch` for auto-compilation, `--minify` for production)
- `update` - Updates to the latest version of Tailwind CSS
- `install` - Manually install the Tailwind CLI (usually automatic)

### Template Tag

The [`tailwind_css`](./templates.py#TailwindCSSExtension) template tag includes the compiled CSS file in your templates. Place it in your base template's `<head>`:

```html
<!DOCTYPE html>
<html>
<head>
    {% tailwind_css %}
</head>
<body>
    <!-- Your content -->
</body>
</html>
```

## Configuration

### Updating Tailwind

The package tracks the Tailwind version in your `pyproject.toml`:

```toml
# pyproject.toml
[tool.plain.tailwind]
version = "3.4.1"
```

When you run `plain tailwind build`, it automatically checks if your local installation matches this version and updates if needed.

To update to the latest version:

```sh
plain tailwind update
```

This downloads the latest version and updates your `pyproject.toml`.

### Adding Custom CSS

Custom CSS should be added to your source CSS file (by default at the root of your project as `tailwind.css`):

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

[Read the Tailwind docs for more about using custom styles →](https://tailwindcss.com/docs/adding-custom-styles)

## Deployment

For production deployments:

1. Add `app/assets/tailwind.min.css` to your `.gitignore`
2. Run `plain tailwind build --minify` as part of your deployment process

The build command automatically installs the Tailwind CLI if it's not present, making deployments seamless.

## Installation

Install the `plain.tailwind` package from [PyPI](https://pypi.org/project/plain.tailwind/):

```bash
uv add plain.tailwind
```

Then add to your `INSTALLED_PACKAGES`:

```python
# settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.tailwind",
]
```

The package stores the Tailwind CLI binary and version information in a `.plain` directory. Add this to your `.gitignore`:

```
.plain/
```
