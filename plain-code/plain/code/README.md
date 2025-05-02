# plain.code

**Preconfigured code formatting and linting.**

The `plain code` command lints and formats Python files using [Ruff](https://astral.sh/ruff), and JavaScript, JSON, and CSS files using [Biome](https://biomejs.dev/). Ruff is installed as a Python dependency, and Biome is managed automatically as a standalone binary (npm is not required).

The most used command is `plain code fix`, which can be run using the alias `plain fix`.

![](https://assets.plainframework.com/docs/plain-fix.png)

If [`plain.dev`](/plain-dev/README.md) is installed then `plain code check` will be run automatically as a part of `plain precommit` to help catch issues before they are committed.

## Configuration

Default configuration is provided by [`ruff_defaults.toml`](plain/code/ruff_defaults.toml) and [`biome_defaults.json`](plain/code/biome_defaults.json).

Generally it's expected that you won't change the configuration! We've tried to pick defaults that "just work" for most projects. If you find yourself needing to customize things, you should probably just move to using the tools themselves directly instead of the `plain.code` package.
