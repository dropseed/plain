# plain-observer changelog

## [0.13.0](https://github.com/dropseed/plain/releases/plain-observer@0.13.0) (2025-10-29)

### What's changed

- Inline JavaScript and CSS extracted to separate asset files for Content Security Policy (CSP) compatibility ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Added CSP nonce support to inline scripts for improved security ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Added comprehensive CSP configuration documentation in README, including required `frame-ancestors 'self'` directive for toolbar panel ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Span and log indentation now uses CSS classes with data attributes instead of inline styles ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Timeline bar positioning now uses CSS custom properties set via JavaScript instead of inline styles ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Copy share URL button now uses data attributes and event delegation instead of inline onclick handlers ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Toolbar iframe now uses HTML attributes instead of inline styles ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-observer@0.12.0) (2025-10-24)

### What's changed

- Admin viewsets now use `presets` instead of `displays` for predefined queryset filters ([0ecc60f](https://github.com/dropseed/plain/commit/0ecc60f19e))
- Removed `logger` field from Log admin interface for simplified display ([ae43138](https://github.com/dropseed/plain/commit/ae43138863))
- Removed `/admin/.*` from default ignored URL patterns, allowing admin pages to be traced ([daadf1a](https://github.com/dropseed/plain/commit/daadf1a53d))

### Upgrade instructions

- If you have custom admin viewsets using the `displays` attribute, rename it to `presets`
- If you reference the `display` property in custom admin code (e.g., `self.display`), rename it to `self.preset`

## [0.11.2](https://github.com/dropseed/plain/releases/plain-observer@0.11.2) (2025-10-20)

### What's changed

- Package configuration migrated from `tool.uv.dev-dependencies` to the standard `dependency-groups.dev` format ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.11.1](https://github.com/dropseed/plain/releases/plain-observer@0.11.1) (2025-10-10)

### What's changed

- Trace list items now update the URL when clicked, allowing direct linking to specific traces ([9f29b68](https://github.com/dropseed/plain/commit/9f29b68a87))
- Improved trace sidebar layout by moving the timestamp to the bottom right and creating better visual hierarchy ([9f29b68](https://github.com/dropseed/plain/commit/9f29b68a87))
- Updated diagnose command prompt text to be less personal in tone ([c82d67b](https://github.com/dropseed/plain/commit/c82d67bfcf))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-observer@0.11.0) (2025-10-08)

### What's changed

- Observer can now be enabled in DEBUG mode using an `Observer` HTTP header (e.g., `Observer: persist` or `Observer: summary`), which takes precedence over cookies ([cba149a](https://github.com/dropseed/plain/commit/cba149a40e))
- Added validation for observer mode values that raises helpful errors in DEBUG mode when invalid values are provided ([cba149a](https://github.com/dropseed/plain/commit/cba149a40e))
- Refactored `Observer` class to accept cookies and headers as constructor parameters, with new `from_request()` and `from_otel_context()` factory methods for improved testability ([cba149a](https://github.com/dropseed/plain/commit/cba149a40e))
- Added AGENTS.md file with helpful commands for AI agents working with Plain Observer ([cba149a](https://github.com/dropseed/plain/commit/cba149a40e))

### Upgrade instructions

- No changes required

## [0.10.1](https://github.com/dropseed/plain/releases/plain-observer@0.10.1) (2025-10-08)

### What's changed

- Fixed content negotiation priority in trace detail and shared views to prefer HTML over JSON by default ([00212835aa](https://github.com/dropseed/plain/commit/00212835aa))

### Upgrade instructions

- No changes required

## [0.10.0](https://github.com/dropseed/plain/releases/plain-observer@0.10.0) (2025-10-07)

### What's changed

- Model configuration now uses `model_options` descriptor instead of `class Meta` for improved consistency with Plain framework patterns ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- Custom QuerySet classes are now defined as descriptors on the model class instead of being configured in Meta ([2578301](https://github.com/dropseed/plain/commit/2578301819))
- Internal model metadata split into separate `model_options` and `_model_meta` attributes for better organization ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.9.1](https://github.com/dropseed/plain/releases/plain-observer@0.9.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package for improved IDE support and type checking ([ffb8624](https://github.com/dropseed/plain/commit/ffb8624d6f))
- Package has been validated with 100% type coverage and added to the type validation script ([ffb8624](https://github.com/dropseed/plain/commit/ffb8624d6f))

### Upgrade instructions

- No changes required

## [0.9.0](https://github.com/dropseed/plain/releases/plain-observer@0.9.0) (2025-09-30)

### What's changed

- Settings renamed from `APP_NAME` to `NAME` and `APP_VERSION` to `VERSION` for consistency with Plain conventions ([4c5f216](https://github.com/dropseed/plain/commit/4c5f2166c1))
- Trace detail and shared views now use `request.get_preferred_type()` for improved content negotiation ([b105ba4](https://github.com/dropseed/plain/commit/b105ba4dd0))

### Upgrade instructions

- No changes required

## [0.8.0](https://github.com/dropseed/plain/releases/plain-observer@0.8.0) (2025-09-30)

### What's changed

- The toolbar panel class has been renamed from `ToolbarPanel` to `ToolbarItem` for better clarity and consistency ([79654db](https://github.com/dropseed/plain/commit/79654db))
- The `template_name` attribute has been renamed to `panel_template_name` in toolbar items ([79654db](https://github.com/dropseed/plain/commit/79654db))
- The registration decorator has been renamed from `register_toolbar_panel` to `register_toolbar_item` ([79654db](https://github.com/dropseed/plain/commit/79654db))

### Upgrade instructions

- If you have custom toolbar panels, rename your class from inheriting `ToolbarPanel` to `ToolbarItem`
- If you use the `template_name` attribute in your toolbar items, rename it to `panel_template_name`
- If you use the `@register_toolbar_panel` decorator, change it to `@register_toolbar_item`

## [0.7.0](https://github.com/dropseed/plain/releases/plain-observer@0.7.0) (2025-09-12)

### What's changed

- Model manager renamed from `objects` to `query` throughout the codebase for consistency with Plain framework conventions ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Updated internal QuerySet configuration to use `queryset_class` instead of `manager_class` in model Meta ([bbaee93](https://github.com/dropseed/plain/commit/bbaee93839))
- Simplified manager initialization by removing explicit `objects` assignment in favor of Meta configuration ([6b60a00](https://github.com/dropseed/plain/commit/6b60a00731))

### Upgrade instructions

- Replace any direct usage of `Trace.objects` with `Trace.query` in your code
- Replace any direct usage of `Span.objects` with `Span.query` in your code
- Replace any direct usage of `Log.objects` with `Log.query` in your code

## [0.6.2](https://github.com/dropseed/plain/releases/plain-observer@0.6.2) (2025-09-09)

### What's changed

- Improved traces sidebar layout by simplifying the display structure and making better use of space ([da789d19](https://github.com/dropseed/plain/commit/da789d1926))

### Upgrade instructions

- No changes required

## [0.6.1](https://github.com/dropseed/plain/releases/plain-observer@0.6.1) (2025-09-09)

### What's changed

- Log messages are now stored in their formatted form instead of as raw log records, improving display consistency and performance ([b646699](https://github.com/dropseed/plain/commit/b646699e46))
- Observer log handler now copies the formatter from the app logger to ensure consistent log formatting ([b646699](https://github.com/dropseed/plain/commit/b646699e46))
- Simplified log display template by removing redundant level display element ([b646699](https://github.com/dropseed/plain/commit/b646699e46))

### Upgrade instructions

- No changes required

## [0.6.0](https://github.com/dropseed/plain/releases/plain-observer@0.6.0) (2025-09-09)

### What's changed

- Added comprehensive log capture and display during trace recording, with logs shown in a unified timeline alongside spans ([9bfe938](https://github.com/dropseed/plain/commit/9bfe938f64))
- Added new Log model with admin interface for managing captured log entries ([9bfe938](https://github.com/dropseed/plain/commit/9bfe938f64))
- Observer now automatically enables debug logging during trace recording to capture more detailed information ([731196](https://github.com/dropseed/plain/commit/731196086f))
- Added app_name and app_version fields to trace records for better application identification ([2870636](https://github.com/dropseed/plain/commit/2870636944))
- Added span count display in trace detail views ([4d22c10](https://github.com/dropseed/plain/commit/4d22c1058d))
- Enhanced database query counting to only include queries with actual query text, providing more accurate metrics ([3d102d3](https://github.com/dropseed/plain/commit/3d102d3796))
- Improved trace limit cleanup logic to properly maintain the configured trace limit ([e9d124b](https://github.com/dropseed/plain/commit/e9d124bccd))
- Added source code location attributes support for spans with file path, line number, and function information ([da36a17](https://github.com/dropseed/plain/commit/da36a17dab))
- Updated Python version requirement to 3.13 minimum ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- No changes required

## [0.5.0](https://github.com/dropseed/plain/releases/plain-observer@0.5.0) (2025-09-03)

### What's changed

- Extended observer summary mode cookie duration from 1 day to 1 week for improved user experience ([bbe8a8a](https://github.com/dropseed/plain/commit/bbe8a8ad54))
- Changed admin navigation icon for Spans from "diagram-3" to "activity" ([2aac07d](https://github.com/dropseed/plain/commit/2aac07de4e))

### Upgrade instructions

- No changes required

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
