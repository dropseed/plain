# plain-admin changelog

## [0.36.0](https://github.com/dropseed/plain/releases/plain-admin@0.36.0) (2025-07-22)

### What's changed

- Admin URL patterns now use `id` instead of `pk` for model object routing (e.g., `/user/<int:id>/` instead of `/user/<int:pk>/`) ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))
- Admin list view templates and JavaScript now reference object IDs consistently using `id` instead of `pk` ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))

### Upgrade instructions

- The `perform_action` admin view methods should be updated to use `target_ids` instead of `target_pks`
- Any custom admin templates or views that reference model object IDs should be updated to use `id` instead of `pk`

## [0.35.1](https://github.com/dropseed/plain/releases/plain-admin@0.35.1) (2025-07-21)

### What's changed

- The toolbar panel template context now includes a `panel` variable, making it easier for custom toolbar panels to reference themselves in templates ([47716ae](https://github.com/dropseed/plain/commit/47716ae))

### Upgrade instructions

- No changes required

## [0.35.0](https://github.com/dropseed/plain/releases/plain-admin@0.35.0) (2025-07-18)

### What's changed

- The built-in QueryStats functionality has been completely removed from plain-admin in favor of the new OpenTelemetry-based observability tools in the `plain-observer` package ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0))
- QueryStats documentation has been removed from the admin README ([97fb69d](https://github.com/dropseed/plain/commit/97fb69d))

### Upgrade instructions

- Remove any querystats-related settings like `ADMIN_QUERYSTATS_IGNORE_URLS` from your configuration

## [0.34.0](https://github.com/dropseed/plain/releases/plain-admin@0.34.0) (2025-07-18)

### What's changed

- The admin toolbar now automatically expands when an exception occurs, making it easier to immediately see exception details ([55a6eaf](https://github.com/dropseed/plain/commit/55a6eaf))
- The admin toolbar now remembers your custom height preference when resized, persisting across page reloads and browser sessions ([b8db44b](https://github.com/dropseed/plain/commit/b8db44b))

### Upgrade instructions

- No changes required

## [0.33.2](https://github.com/dropseed/plain/releases/plain-admin@0.33.2) (2025-07-07)

### What's changed

- No user-facing changes in this release. Internal CSS cleanup and linter adjustments were made to the bundled admin styles ([3265f5f](https://github.com/dropseed/plain/commit/3265f5f)).

### Upgrade instructions

- No changes required

## [0.33.1](https://github.com/dropseed/plain/releases/plain-admin@0.33.1) (2025-06-26)

### What's changed

- No user-facing changes in this release. Internal documentation formatting was improved ([2fc81de](https://github.com/dropseed/plain/commit/2fc81de)).

### Upgrade instructions

- No changes required

## [0.33.0](https://github.com/dropseed/plain/releases/plain-admin@0.33.0) (2025-06-23)

### What's changed

- The QueryStats browser toolbar now logs a concise summary message in the developer console instead of the full `PerformanceEntry` object, making query-timing information easier to scan ([fcd92a6](https://github.com/dropseed/plain/commit/fcd92a6)).
- QueryStats middleware now uses `plain.models.db_connection`, aligning with the new single-`DATABASE` configuration and removing the dependency on `DEFAULT_DB_ALIAS` ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).

### Upgrade instructions

- No changes required
