---
name: plain-principles
description: Provides Plain framework context and coding conventions. Use when starting work on a Plain project or unsure about framework patterns.
---

# Plain Framework

Plain is a Python web framework originally forked from Django. While it has a lot in common with Django, there are significant differences. Don't solely rely on Django knowledge when working with Plain.

## Templates

Plain templates use Jinja2, not Django's template engine.

## Code Style

- Add `from __future__ import annotations` at the top of Python files
- Keep imports at the top of the file unless avoiding circular imports

## CLI

The `plain` CLI is the main entrypoint.

```
uv run plain --help
```

Lists all available commands including those from installed packages.
