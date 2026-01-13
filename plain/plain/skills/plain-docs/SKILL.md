---
name: plain-docs
description: Retrieves detailed documentation for Plain packages. Use when looking up package APIs or feature details.
---

# Getting Documentation

## List Available Packages

```
uv run plain docs --list
```

## Get Package Documentation

```
uv run plain docs <package> --source
```

Examples:

- `uv run plain docs models --source` - Models and database
- `uv run plain docs templates --source` - Jinja2 templates
- `uv run plain docs assets --source` - Static assets
- `uv run plain docs tailwind --source` - Tailwind CSS integration
