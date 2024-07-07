# Templates

Render HTML templates using Jinja.

Templates are typically rendered in `TemplateViews`,
but you can also render them directly to strings for emails or other use cases.

```python
from plain.templates import Template


Template("comment.md").render({
    "message": "Hello, world!",
})
```

Template files can be located in either a root `app/templates`,
or the `templates` directory in any installed packages.

[Customizing Jinja](./jinja/README.md)
