---
paths:
  - "**/*.py"
---

# Code Quality

## Fix Formatting and Linting

```
uv run plain fix [path]
```

Automatically fixes formatting and linting issues using ruff and oxlint/oxfmt.

Options:

- `--unsafe-fixes` - Apply ruff unsafe fixes
- `--add-noqa` - Add noqa comments to suppress errors

## Check Without Fixing

```
uv run plain code check [path]
```

Runs ruff, ty (type checking), oxlint/oxfmt, and annotation coverage checks without auto-fixing.

## Code Style

- Add `from __future__ import annotations` at the top of Python files
- Keep imports at the top of the file unless avoiding circular imports
- Don't include args/returns in docstrings if already type annotated
