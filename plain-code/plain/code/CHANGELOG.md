# plain-code changelog

## [0.11.3](https://github.com/dropseed/plain/releases/plain-code@0.11.3) (2025-11-03)

### What's changed

- Improved CLI command descriptions to be more concise and user-friendly ([fdb9e80](https://github.com/dropseed/plain/commit/fdb9e80))
- The `plain fix` command is now marked as a common command and registered as a shortcut for `plain code fix` ([73d3a48](https://github.com/dropseed/plain/commit/73d3a48), [7910a06](https://github.com/dropseed/plain/commit/7910a06))

### Upgrade instructions

- No changes required

## [0.11.2](https://github.com/dropseed/plain/releases/plain-code@0.11.2) (2025-10-31)

### What's changed

- Added BSD-3-Clause license identifier to package metadata ([8477355](https://github.com/dropseed/plain/commit/8477355))

### Upgrade instructions

- No changes required

## [0.11.1](https://github.com/dropseed/plain/releases/plain-code@0.11.1) (2025-10-27)

### What's changed

- Improved `plain code check` output with styled command labels and a clearer error message when checks fail ([5e75a0d](https://github.com/dropseed/plain/commit/5e75a0d))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-code@0.11.0) (2025-10-22)

### What's changed

- All CLI commands now skip runtime setup for faster execution by using the `@without_runtime_setup` decorator ([b7358d7](https://github.com/dropseed/plain/commit/b7358d7))

### Upgrade instructions

- No changes required

## [0.10.2](https://github.com/dropseed/plain/releases/plain-code@0.10.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the codebase for improved IDE support and type checking ([7455fa0](https://github.com/dropseed/plain/commit/7455fa0))

### Upgrade instructions

- No changes required

## [0.10.1](https://github.com/dropseed/plain/releases/plain-code@0.10.1) (2025-09-25)

### What's changed

- Improved Biome download performance by using larger chunk sizes (1MB instead of 8KB) for faster binary downloads ([9bf4eca](https://github.com/dropseed/plain/commit/9bf4eca))

### Upgrade instructions

- No changes required

## [0.10.0](https://github.com/dropseed/plain/releases/plain-code@0.10.0) (2025-09-19)

### What's changed

- Minimum Python version increased from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307))

### Upgrade instructions

- Ensure your Python environment is running Python 3.13 or later before upgrading

## [0.9.2](https://github.com/dropseed/plain/releases/plain-code@0.9.2) (2025-07-30)

### What's changed

- Skip Biome installation and updates when Biome is disabled in configuration ([b8beb5c](https://github.com/dropseed/plain/commit/b8beb5c))
- Enhanced README with better structure, usage examples, and configuration documentation ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1))

### Upgrade instructions

- No changes required

## [0.9.1](https://github.com/dropseed/plain/releases/plain-code@0.9.1) (2025-07-18)

### What's changed

- Improved error handling by using `click.UsageError` instead of `print` and `sys.exit` for better CLI error messages ([88f06c5](https://github.com/dropseed/plain/commit/88f06c5))

### Upgrade instructions

- No changes required

## [0.9.0](https://github.com/dropseed/plain/releases/plain-code@0.9.0) (2025-07-03)

### What's changed

- Updated Biome integration to support the new **Biome 2** release. The download logic now uses the new `@biomejs/biome@<version>` tag format and the built-in default configuration has been modernised (`root: true`, `files.includes`, etc.) ([83fa906](https://github.com/dropseed/plain/commit/83fa906)).
- A progress bar is now displayed while the Biome binary is being downloaded so you can see the download progress in real time ([ec637aa](https://github.com/dropseed/plain/commit/ec637aa)).

### Upgrade instructions

- If you have pinned a specific Biome version in your `pyproject.toml` under `[tool.plain.code.biome]`, make sure it is compatible with Biome 2 (for example, `version = "2.0.0"`). Otherwise, use `plain code update` to update to Biome 2.

## [0.8.3](https://github.com/dropseed/plain/releases/plain-code@0.8.3) (2025-06-26)

### What's changed

- Added this `CHANGELOG.md` file to start tracking changes for the `plain.code` package ([82710c3](https://github.com/dropseed/plain/commit/82710c3)).
- No functional changes were introduced in this release.

### Upgrade instructions

- No changes required
