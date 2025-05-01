# Biome JS Formatter Support

This plugin now integrates [Biome](https://github.com/biomejs/biome) as a standalone binary.

When enabled, `plain code check` will run `biome fmt --check <path>`, and
`plain code fix` will run `biome fmt <path>` after Ruff.

Configuration (in your project's `pyproject.toml`):

```toml
[tool.plain.code.biome]
enabled = true    # whether to run Biome formatting (default: true)
version = "1.9.4"  # optional; Biome version to install (without leading 'v')
```
