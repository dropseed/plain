# plain.pages

**Serve static pages, markdown, and assets from templates/pages directories.**

- [Overview](#overview)
- [Page types](#page-types)
    - [HTML pages](#html-pages)
    - [Markdown pages](#markdown-pages)
    - [Redirect pages](#redirect-pages)
    - [Assets](#assets)
    - [Template pages](#template-pages)
- [Frontmatter](#frontmatter)
- [Custom views](#custom-views)
- [Installation](#installation)

## Overview

The plain.pages package automatically discovers and serves static pages from `templates/pages` directories in your app and installed packages. Pages can be HTML, Markdown, redirects, or static assets, with support for frontmatter variables and template rendering.

```python
# app/templates/pages/about.md
---
title: About Us
---

# About Our Company

We build great software.
```

This creates a page at `/about/` that renders the markdown content with the title "About Us".

Pages are discovered from:

- `{package}/templates/pages/` for each installed package
- `app/templates/pages/` in your main application

The file path determines the URL:

- `index.html` or `index.md` → `/`
- `about.html` or `about.md` → `/about/`
- `docs/getting-started.md` → `/docs/getting-started/`
- `styles.css` → `/styles.css` (served as static asset)

## Page types

### HTML pages

HTML files are rendered as templates with access to the standard template context:

```html
<!-- app/templates/pages/features.html -->
---
title: Features
---

<h1>{{ page.title }}</h1>
<p>Current user: {{ request.user }}</p>
```

### Markdown pages

Markdown files (`.md`) are automatically converted to HTML:

```markdown
<!-- app/templates/pages/guide.md -->
---
title: User Guide
template_name: custom-page.html
---

# User Guide

This is **markdown** content with [links](/other-page/).
```

### Redirect pages

Files with `.redirect` extension create redirects:

```yaml
# app/templates/pages/old-url.redirect
---
url: /new-url/
temporary: false
---
```

### Assets

Any file that isn't HTML, Markdown, or a redirect is served as a static asset:

```
app/templates/pages/
├── favicon.ico
├── robots.txt
├── images/
│   └── logo.png
└── docs/
    └── guide.pdf
```

These are served at their exact paths: `/favicon.ico`, `/images/logo.png`, etc.

### Template pages

Files containing `.template.` in their name are skipped and not served as pages. Use these for shared template fragments:

```
app/templates/pages/
├── base.template.html  # Not served
└── index.html          # Served at /
```

## Frontmatter

Pages support YAML frontmatter for configuration:

```yaml
---
title: Custom Title
template_name: my-template.html
render_plain: true
custom_var: value
---
```

Available frontmatter options:

- `title`: Page title (defaults to filename)
- `template_name`: Custom template to use
- `render_plain`: Skip template rendering (for markdown)
- `url`: Redirect URL (for .redirect files)
- `temporary`: Redirect type (for .redirect files)
- Any custom variables accessible via `page.vars`

## Custom views

The package provides view classes you can extend:

```python
from plain.pages.views import PageView

class CustomPageView(PageView):
    def get_template_context(self):
        context = super().get_template_context()
        context["extra_data"] = self.get_extra_data()
        return context
```

The main view classes are:

- [`PageView`](./views.py#PageView): Renders HTML and Markdown pages
- [`PageRedirectView`](./views.py#PageRedirectView): Handles redirects
- [`PageAssetView`](./views.py#PageAssetView): Serves static assets

## Installation

Install the `plain.pages` package from [PyPI](https://pypi.org/project/plain.pages/):

```bash
uv add plain.pages
```
