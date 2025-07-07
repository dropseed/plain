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
