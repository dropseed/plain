# plain.code

**Preconfigured code formatting and linting.**

- [Overview](#overview)
- [Configuration](#configuration)
- [Installation](#installation)

## Overview

The `plain code` command provides comprehensive code quality tools:

- **[Ruff](https://astral.sh/ruff)** - Python linting and formatting
- **[ty](https://astral.sh/ty)** - Python type checking
- **[Biome](https://biomejs.dev/)** - JavaScript, JSON, and CSS formatting

Ruff and ty are installed as Python dependencies. Biome is managed automatically as a standalone binary (npm is not required).

The most used command is `plain code fix`, which can be run using the alias `plain fix`:

```bash
plain fix
```

This will automatically fix linting issues and format your code according to the configured rules.

![](https://assets.plainframework.com/docs/plain-fix.png)

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
```

If [`plain.dev`](/plain-dev/README.md) is installed then `plain code check` will be run automatically as a part of `plain precommit` to help catch issues before they are committed.

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
```

For more advanced configuration options, see [`get_code_config`](./cli.py#get_code_config).

Generally it's expected that you won't change the configuration! We've tried to pick defaults that "just work" for most projects. If you find yourself needing to customize things, you should probably just move to using the tools themselves directly instead of the `plain.code` package.

## Installation

Install the `plain.code` package from [PyPI](https://pypi.org/project/plain.code/):

```bash
uv add plain.code
```
