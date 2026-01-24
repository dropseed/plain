# plain.pages

**Serve static pages, markdown, and assets from templates/pages directories.**

- [Overview](#overview)
- [Page types](#page-types)
    - [HTML pages](#html-pages)
    - [Markdown pages](#markdown-pages)
    - [Redirect pages](#redirect-pages)
    - [Assets](#assets)
    - [Template pages](#template-pages)
- [Serving raw markdown](#serving-raw-markdown)
    - [Linking to markdown URLs](#linking-to-markdown-urls)
- [Frontmatter](#frontmatter)
- [Custom views](#custom-views)
- [Settings](#settings)
- [FAQs](#faqs)
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
<p>Current user: {{ get_current_user() }}</p>
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

## Serving raw markdown

You can optionally serve raw markdown content (without frontmatter) alongside rendered HTML pages. When enabled, markdown pages can be accessed as raw markdown via:

1. **Accept header negotiation** - Send `Accept: text/markdown` or `Accept: text/plain` to get raw markdown
2. **Separate .md URLs** - Access `/docs/guide.md` alongside `/docs/guide/`

```python
# settings.py
PAGES_SERVE_MARKDOWN = True
```

With this setting enabled:

- `/docs/guide/` with `Accept: text/html` → Rendered HTML page
- `/docs/guide/` with `Accept: text/markdown` → Raw markdown content
- `/docs/guide.md` → Raw markdown content (without frontmatter)

The raw markdown serves with `text/plain` content type, making it useful for:

- External markdown processors
- API consumers needing markdown source
- Documentation tools that need raw content
- Command-line tools like curl or httpie

**Note**: This feature is disabled by default. Only enable it if you need to serve raw markdown content.

### Linking to markdown URLs

When markdown serving is enabled, you can link to the raw markdown version from templates:

```html
<!-- In your page template -->
<a href="{{ page.get_markdown_url() }}">View Source</a>
<a href="{{ page.get_markdown_url() }}">Download Markdown</a>
```

The `get_markdown_url()` method returns:

- The markdown URL (e.g., `/docs/guide.md`) if the page is markdown and the feature is enabled
- `None` if the page is not markdown or the feature is disabled

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

You can extend the view classes to customize page rendering:

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
- [`PageMarkdownView`](./views.py#PageMarkdownView): Serves raw markdown content

## Settings

| Setting                | Default | Env var |
| ---------------------- | ------- | ------- |
| `PAGES_SERVE_MARKDOWN` | `False` | -       |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I use a custom base template for markdown pages?

Set the `template_name` in frontmatter to specify your own template. Your template should include `{{ page.content }}` to render the markdown content.

#### Can I use template tags and filters in markdown files?

Yes. Unless you set `render_plain: true` in the frontmatter, markdown files are processed as templates first, then converted to HTML. You can use any template tags and filters available in your project.

#### How do I access frontmatter variables in templates?

Custom frontmatter variables are available through `page.vars`. For example, if your frontmatter includes `author: Jane Doe`, you can access it with `{{ page.vars.author }}`.

#### Why isn't my page showing up?

Check that your file is in a `templates/pages/` directory and doesn't contain `.template.` in the filename. Template files are intentionally skipped.

## Installation

Install the `plain.pages` package from [PyPI](https://pypi.org/project/plain.pages/):

```bash
uv add plain.pages
```
