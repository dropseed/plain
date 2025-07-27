# plain.code

**Preconfigured code formatting and linting.**

- [Overview](#overview)
- [Configuration](#configuration)
- [Installation](#installation)

## Overview

The `plain code` command lints and formats Python files using [Ruff](https://astral.sh/ruff), and JavaScript, JSON, and CSS files using [Biome](https://biomejs.dev/). Ruff is installed as a Python dependency, and Biome is managed automatically as a standalone binary (npm is not required).

The most used command is `plain code fix`, which can be run using the alias `plain fix`:

```bash
plain fix
```

This will automatically fix linting issues and format your code according to the configured rules.

![](https://assets.plainframework.com/docs/plain-fix.png)

If [`plain.dev`](/plain-dev/README.md) is installed then `plain code check` will be run automatically as a part of `plain precommit` to help catch issues before they are committed.

## Configuration

Default configuration is provided by [`ruff_defaults.toml`](./ruff_defaults.toml) and [`biome_defaults.json`](./biome_defaults.json).

You can customize the behavior in your `pyproject.toml`:

```toml
[tool.plain.code]
exclude = ["path/to/exclude"]

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
