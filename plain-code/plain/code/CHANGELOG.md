# plain-code changelog

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
