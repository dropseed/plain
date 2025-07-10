# plain-code changelog

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
