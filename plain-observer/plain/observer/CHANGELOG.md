# plain-observer changelog

## [0.4.0](https://github.com/dropseed/plain/releases/plain-observer@0.4.0) (2025-08-27)

### What's changed

- Toolbar functionality has been moved to a new `plain.toolbar` package, with observer-specific toolbar code now in a dedicated `toolbar.py` file ([e49d54b](https://github.com/dropseed/plain/commit/e49d54bfea))

### Upgrade instructions

- No changes required

## [0.3.7](https://github.com/dropseed/plain/releases/plain-observer@0.3.7) (2025-08-22)

### What's changed

- Improved admin interface code organization by reordering navigation icon and model field declarations ([5a6479a](https://github.com/dropseed/plain/commit/5a6479ac79))

### Upgrade instructions

- No changes required

## [0.3.6](https://github.com/dropseed/plain/releases/plain-observer@0.3.6) (2025-07-31)

### What's changed

- Added database index on `span_id` field in the Span model for improved query performance ([f836542](https://github.com/dropseed/plain/commit/f836542df6))
- Database tracing is now suppressed when querying for span links to prevent recursive tracing loops ([f836542](https://github.com/dropseed/plain/commit/f836542df6))

### Upgrade instructions

- No changes required

## [0.3.5](https://github.com/dropseed/plain/releases/plain-observer@0.3.5) (2025-07-30)

### What's changed

- Improved observer toolbar button text clarity for empty states - "Recording" now shows as "Recording (no summary)" and "Summary" shows as "No summary" ([143c2a6](https://github.com/dropseed/plain/commit/143c2a61a7))
- Fixed observer auto-enable functionality by adding POST handler for summary mode actions ([cc415e0](https://github.com/dropseed/plain/commit/cc415e0af7))

### Upgrade instructions

- No changes required

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
