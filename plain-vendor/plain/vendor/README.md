# plain.vendor

**Download and manage vendored CSS and JavaScript dependencies from CDNs.**

- [Overview](#overview)
- [Adding dependencies](#adding-dependencies)
- [Syncing dependencies](#syncing-dependencies)
- [Updating dependencies](#updating-dependencies)
- [Configuration options](#configuration-options)
    - [Custom filenames](#custom-filenames)
    - [Source maps](#source-maps)
    - [Version placeholders](#version-placeholders)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use `plain vendor` to download JavaScript and CSS files from CDNs and store them locally in your project. This keeps third-party assets under version control and avoids runtime dependencies on external CDNs.

Dependencies are configured in your `pyproject.toml` and downloaded to `app/assets/vendor/`.

```toml
# pyproject.toml
[tool.plain.vendor.dependencies]
htmx = {url = "https://unpkg.com/htmx.org@{version}/dist/htmx.min.js", installed = "2.0.4"}
alpine = {url = "https://cdn.jsdelivr.net/npm/alpinejs@{version}/dist/cdn.min.js", installed = "3.14.8"}
```

After configuring dependencies, run `plain vendor sync` to download them:

```bash
plain vendor sync
```

The files are saved to `app/assets/vendor/` and can be included in your templates:

```html
<script src="{{ 'vendor/htmx.min.js'|asset }}"></script>
<script src="{{ 'vendor/cdn.min.js'|asset }}"></script>
```

## Adding dependencies

You can add a new dependency directly from the command line:

```bash
plain vendor add https://unpkg.com/htmx.org/dist/htmx.min.js
```

This downloads the file, extracts the version from the URL, and adds an entry to your `pyproject.toml`. You can also specify a custom name:

```bash
plain vendor add https://unpkg.com/htmx.org/dist/htmx.min.js --name htmx
```

## Syncing dependencies

The `sync` command clears all existing vendored files and re-downloads everything from scratch:

```bash
plain vendor sync
```

Use this when you first clone a project or want to ensure your vendored files match your configuration.

## Updating dependencies

The `update` command checks for newer versions and updates your `pyproject.toml`:

```bash
# Update all dependencies
plain vendor update

# Update specific dependencies
plain vendor update htmx alpine
```

The update process tries several strategies to find newer versions:

1. Requests the "latest" tag (supported by many CDNs)
2. Increments version numbers to probe for new releases

## Configuration options

### Custom filenames

If you want to rename a file when it's downloaded, use the `filename` option:

```toml
[tool.plain.vendor.dependencies]
htmx = {url = "https://unpkg.com/htmx.org@{version}/dist/htmx.min.js", installed = "2.0.4", filename = "htmx.js"}
```

### Source maps

You can automatically download source maps alongside your vendored files:

```toml
[tool.plain.vendor.dependencies]
htmx = {url = "https://unpkg.com/htmx.org@{version}/dist/htmx.min.js", installed = "2.0.4", sourcemap = true}
```

When `sourcemap = true`, the tool appends `.map` to the filename and downloads from the same directory. For non-standard source map filenames, provide the filename directly:

```toml
[tool.plain.vendor.dependencies]
example = {url = "https://example.com/lib.min.js", installed = "1.0.0", sourcemap = "lib.min.js.map"}
```

You can also use the `--sourcemap` flag when adding dependencies:

```bash
plain vendor add https://unpkg.com/htmx.org/dist/htmx.min.js --sourcemap
```

### Version placeholders

URLs can include a `{version}` placeholder that gets replaced with the installed version number:

```toml
htmx = {url = "https://unpkg.com/htmx.org@{version}/dist/htmx.min.js", installed = "2.0.4"}
```

When you run `plain vendor sync`, the placeholder is replaced with `2.0.4`. This makes it easy to see which version is installed and enables the update command to try newer versions.

## FAQs

#### What file types are supported?

The vendor tool accepts JavaScript (`application/javascript`, `text/javascript`), CSS (`text/css`), and JSON (`application/json`) files. Other content types will raise an error.

#### Where are vendored files stored?

All vendored files are downloaded to `app/assets/vendor/`. This directory is created automatically if it doesn't exist.

#### How does version detection work?

When you add a dependency or update to a new version, the tool parses version numbers from the final URL (after any redirects). It looks for patterns like `1.2.3` or `1.2` in the URL path.

#### What happens if a CDN is unavailable?

The sync and update commands will fail with an error if any dependency cannot be downloaded. You'll see which dependencies failed in the output.

## Installation

Install the `plain.vendor` package from [PyPI](https://pypi.org/project/plain.vendor/):

```bash
uv add plain.vendor
```

After installation, the `plain vendor` command becomes available. Configure your dependencies in `pyproject.toml`:

```toml
[tool.plain.vendor.dependencies]
htmx = {url = "https://unpkg.com/htmx.org@{version}/dist/htmx.min.js", installed = "2.0.4"}
```

Then run the sync command to download them:

```bash
plain vendor sync
```

Your vendored files will be available in `app/assets/vendor/` and can be referenced in templates using the `asset` template filter.
