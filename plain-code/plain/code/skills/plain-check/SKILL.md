---
name: plain-check
description: Runs code quality checks including ruff, type checking, and biome. Use for linting, formatting, or preflight validation.
---

# Code Quality

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

## Preflight Checks

```
uv run plain preflight
```

Validates Plain configuration.
