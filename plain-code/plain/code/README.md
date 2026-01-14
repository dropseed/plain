# plain.code

**Preconfigured code formatting and linting.**

- [Overview](#overview)
- [Commands](#commands)
    - [`plain fix`](#plain-fix)
    - [`plain code check`](#plain-code-check)
    - [`plain code annotations`](#plain-code-annotations)
- [Configuration](#configuration)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain.code provides comprehensive code quality tools with sensible defaults:

- **[Ruff](https://astral.sh/ruff)** - Python linting and formatting
- **[ty](https://astral.sh/ty)** - Python type checking
- **[Biome](https://biomejs.dev/)** - JavaScript, JSON, and CSS formatting

Ruff and ty are installed as Python dependencies. Biome is managed automatically as a standalone binary (npm is not required).

## Commands

### `plain fix`

The most used command is [`plain fix`](./cli.py#fix), which automatically fixes linting issues and formats your code:

```bash
plain fix
```

![](https://assets.plainframework.com/docs/plain-fix.png)

You can also apply unsafe fixes or add noqa comments to suppress errors:

```bash
# Apply Ruff's unsafe fixes
plain fix --unsafe-fixes

# Add noqa comments instead of fixing
plain fix --add-noqa
```

### `plain code check`

To check your code without making changes (including type checking):

```bash
plain code check
```

You can skip specific tools if needed:

```bash
# Skip type checking during rapid development
plain code check --skip-ty

# Only run type checks
plain code check --skip-ruff --skip-biome

# Skip Biome checks
plain code check --skip-biome

# Skip annotation coverage checks
plain code check --skip-annotations
```

If [`plain.dev`](/plain-dev/README.md) is installed, `plain code check` will be run automatically as a part of `plain pre-commit` to help catch issues before they are committed.

### `plain code annotations`

Check the type annotation coverage of your codebase:

```bash
plain code annotations
```

This outputs a summary like `85.2% typed (23/27 functions)`.

To see which functions are missing annotations:

```bash
plain code annotations --details
```

You can also output the results as JSON for use in CI or other tools:

```bash
plain code annotations --json
```

## Configuration

Default configuration is provided by [`ruff_defaults.toml`](./ruff_defaults.toml) and [`biome_defaults.json`](./biome_defaults.json).

You can customize the behavior in your `pyproject.toml`:

```toml
[tool.plain.code]
exclude = ["path/to/exclude"]

[tool.plain.code.ty]
enabled = true  # Set to false to disable ty

[tool.plain.code.biome]
enabled = true  # Set to false to disable Biome
version = "1.5.3"  # Pin to a specific version

[tool.plain.code.annotations]
enabled = true  # Set to false to disable annotation checks
exclude = ["migrations"]  # Exclude specific patterns
```

For more advanced configuration options, see [`get_code_config`](./cli.py#get_code_config).

Generally you won't need to change the configuration. The defaults are designed to "just work" for most projects. If you find yourself needing extensive customization, consider using the underlying tools (Ruff, ty, Biome) directly instead.

## FAQs

#### How do I install or update Biome manually?

Biome is installed automatically when you run `plain fix` or `plain code check`. If you need to manage it manually:

```bash
# Install Biome (or reinstall if corrupted)
plain code install

# Force reinstall even if up to date
plain code install --force

# Update to the latest version
plain code update
```

#### Why are test files excluded from annotation coverage?

Test files (`test_*.py`, `*_test.py`, and files in `tests/` or `test/` directories) are excluded by default because they typically contain many small helper functions where type annotations add noise without providing significant value. You can customize this behavior via the `exclude` option in the annotations configuration.

#### How do I check a specific directory?

All commands accept a path argument:

```bash
plain fix path/to/directory
plain code check path/to/directory
plain code annotations path/to/directory
```

## Installation

Install the `plain.code` package from [PyPI](https://pypi.org/project/plain.code/):

```bash
uv add plain.code
```
