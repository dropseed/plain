## [0.3.4](https://github.com/dropseed/plain/releases/plain-upgrade@0.3.4) (2025-07-18)

### What's changed

- The generated upgrade prompt now provides more specific guidance about migrate backups, warning against using `--no-backup` option instead of the general "without backup enabled" ([ac5e642](https://github.com/dropseed/plain/commit/ac5e642df4a554368f7937459d39a0b44b598109))

### Upgrade instructions

- No changes required.

## [0.3.3](https://github.com/dropseed/plain/releases/plain-upgrade@0.3.3) (2025-07-18)

### What's changed

- The generated upgrade prompt now includes `plain fix --unsafe-fixes` in the post-upgrade instructions to automatically fix code style issues before running pre-commit checks ([c7936fa](https://github.com/dropseed/plain/commit/c7936fa546f50d2cbc10a712f9bc4089315d2b8a))

### Upgrade instructions

- No changes required.

## [0.3.2](https://github.com/dropseed/plain/releases/plain-upgrade@0.3.2) (2025-07-18)

### What's changed

- The generated upgrade prompt now provides clearer, more detailed instructions with numbered steps and improved formatting for better readability ([37fa6f3](https://github.com/dropseed/plain/commit/37fa6f3))
- Documentation now uses Claude as the example AI agent command instead of Codex ([04e550b](https://github.com/dropseed/plain/commit/04e550b))

### Upgrade instructions

- No changes required.

## [0.3.1](https://github.com/dropseed/plain/releases/plain-upgrade@0.3.1) (2025-07-07)

### What's changed

- The generated upgrade prompt now explicitly states that you can skip a package version if its changelog says "No changes required" ([9a9e79a](https://github.com/dropseed/plain/commit/9a9e79a)).

### Upgrade instructions

- No changes required.

## [0.3.0](https://github.com/dropseed/plain/releases/plain-upgrade@0.3.0) (2025-06-27)

### What's changed

- `plain-upgrade` no longer requires the current working directory to be inside a Git repository, making it easier to run in fresh projects or CI environments ([371f35f](https://github.com/dropseed/plain/commit/371f35f)).
- The generated upgrade prompt now prefixes follow-up commands with `uv run` (e.g. `uv run plain-changelog` and `uv run plain pre-commit`) so they execute inside the same virtual environment ([3f71c44](https://github.com/dropseed/plain/commit/3f71c44)).
- Documentation improvements and clearer package description (no functional changes) ([a22dc9c](https://github.com/dropseed/plain/commit/a22dc9c)).

### Upgrade instructions

- No changes required.

## [0.2.0](https://github.com/dropseed/plain/releases/plain-upgrade@0.2.0) (2025-06-27)

### What's changed

- The generated upgrade prompt now instructs you to run `plain pre-commit` once all package upgrades are complete, replacing the previous guidance to run `plain preflight` and `plain test` separately ([a0e27a8](https://github.com/dropseed/plain/commit/a0e27a8c390b53a67bdc7a3d823edcaf50c7204b)).

### Upgrade instructions

- No changes required.
