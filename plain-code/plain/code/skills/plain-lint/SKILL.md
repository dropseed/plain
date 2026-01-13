---
name: plain-lint
description: Runs linting and formatting checks using ruff, ty, and biome. Use for quick code quality feedback during development.
---

# Linting and Formatting

## Check for Issues

```
uv run plain code check [path]
```

Runs ruff, ty (type checking), and biome checks.

## Fix Issues

```
uv run plain fix [path]
```

Automatically fixes formatting and linting issues.

Options:

- `--unsafe-fixes` - Apply ruff unsafe fixes
- `--add-noqa` - Add noqa comments to suppress errors
