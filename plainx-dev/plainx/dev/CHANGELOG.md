# plainx-dev changelog

## [0.1.4](https://github.com/dropseed/plain/releases/plainx-dev@0.1.4) (2026-03-29)

### What's changed

- Updated references from `migrations make` to `migrations create`. ([adf021688bf3](https://github.com/dropseed/plain/commit/adf021688bf3))

### Upgrade instructions

- No changes required.

## [0.1.3](https://github.com/dropseed/plain/releases/plainx-dev@0.1.3) (2026-03-25)

### What's changed

- Added `SettingsReference` migration warning rule — reminds package developers to fix auto-generated migrations that hardcode the host app's concrete model instead of using `settings.AUTH_USER_MODEL` ([bd5bfc3ec9cf](https://github.com/dropseed/plain/commit/bd5bfc3ec9cf))

### Upgrade instructions

- No changes required.

## [0.1.2](https://github.com/dropseed/plain/releases/plainx-dev@0.1.2) (2026-03-24)

### What's changed

- Added `disable-model-invocation` safety flag to the `plainx-release` skill ([669e52eda37d](https://github.com/dropseed/plain/commit/669e52eda37d))

### Upgrade instructions

- No changes required.

## [0.1.1](https://github.com/dropseed/plain/releases/plainx-dev@0.1.1) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.1.0](https://github.com/dropseed/plain/releases/plainx-dev@0.1.0) (2026-02-05)

Initial release.

- `/plainx-release` skill for releasing plainx packages with guided workflow
- Version bump suggestions based on commit analysis
- First release detection (0.0.0 convention)
- Changelog generation from code diffs
- GitHub Actions workflow template for PyPI trusted publishing
