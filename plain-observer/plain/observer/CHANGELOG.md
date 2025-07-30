# plain-observer changelog

## [0.3.4](https://github.com/dropseed/plain/releases/plain-observer@0.3.4) (2025-07-30)

### What's changed

- Fixed URL configuration examples in installation documentation to use `ObserverRouter` instead of string path ([f55ac7d](https://github.com/dropseed/plain/commit/f55ac7d491))
- Enhanced README with table of contents, PyPI installation link, and post-installation usage instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.3.3](https://github.com/dropseed/plain/releases/plain-observer@0.3.3) (2025-07-25)

### What's changed

- Added `--print` option to the `plain observer diagnose` command to print prompts without running agents ([9721331](https://github.com/dropseed/plain/commit/9721331e40))
- The `plain observer diagnose` command now uses the shared `prompt_agent` utility for better consistency ([de1fa72](https://github.com/dropseed/plain/commit/de1fa7253a))
- Added comprehensive installation instructions to the README including package installation, URL configuration, and migration steps ([950939b](https://github.com/dropseed/plain/commit/950939b619))

### Upgrade instructions

- No changes required

## [0.3.2](https://github.com/dropseed/plain/releases/plain-observer@0.3.2) (2025-07-25)

### What's changed

- The diagnose agent command now instructs the AI to examine the codebase before making suggestions ([f5ae388](https://github.com/dropseed/plain/commit/f5ae388833))

### Upgrade instructions

- No changes required

## [0.3.1](https://github.com/dropseed/plain/releases/plain-observer@0.3.1) (2025-07-23)

### What's changed

- Added delete actions to the admin interface for both Traces and Spans, allowing bulk deletion of selected items ([0d85670](https://github.com/dropseed/plain/commit/0d85670412))
- Added bootstrap icons to admin navigation (activity icon for Traces, diagram-3 icon for Spans) ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0e2c))

### Upgrade instructions

- No changes required

## [0.3.0](https://github.com/dropseed/plain/releases/plain-observer@0.3.0) (2025-07-22)

### What's changed

- Database models now use the new `PrimaryKeyField` instead of `BigAutoField` for primary keys ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))
- Admin interface updated to use `id` instead of `pk` for ordering and references ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required

## [0.2.0](https://github.com/dropseed/plain/releases/plain-observer@0.2.0) (2025-07-21)

### What's changed

- Added comprehensive CLI commands for trace management including `plain observer traces`, `plain observer trace <id>`, and `plain observer spans` ([90f916b](https://github.com/dropseed/plain/commit/90f916b676))
- Added trace sharing functionality allowing traces to be shared via public URLs ([90f916b](https://github.com/dropseed/plain/commit/90f916b676))
- Added `plain observer diagnose` command with JSON and URL output options for troubleshooting ([71936e88a5](https://github.com/dropseed/plain/commit/71936e88a5))
- Improved trace detail UI with better formatting and navigation ([90f916b](https://github.com/dropseed/plain/commit/90f916b676))
- Removed the custom trace detail UI from the admin interface, now uses standard admin detail view ([0c277fc](https://github.com/dropseed/plain/commit/0c277fc076))
- Enhanced raw agent prompt output styling ([684f208](https://github.com/dropseed/plain/commit/684f2087fc))

### Upgrade instructions

- No changes required

## [0.1.0](https://github.com/dropseed/plain/releases/plain-observer@0.1.0) (2025-07-19)

### What's changed

- Initial release of plain-observer package providing OpenTelemetry-based observability and monitoring for Plain applications ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))
- Added real-time trace monitoring with summary and persist modes via signed cookies ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))
- Added admin interface for viewing detailed trace information and spans ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))
- Added toolbar integration showing performance summaries for current requests ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))
- Observer can now combine with existing OpenTelemetry trace providers instead of replacing them ([7e55779](https://github.com/dropseed/plain/commit/7e55779548))

### Upgrade instructions

- No changes required
