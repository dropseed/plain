# plain-admin changelog

## [0.37.0](https://github.com/dropseed/plain/releases/plain-admin@0.37.0) (2025-07-23)

### What's changed

- Admin buttons are now smaller with reduced padding and font size for better UI density ([d409b910f4](https://github.com/dropseed/plain/commit/d409b910f4))
- Bootstrap icons have been added to the admin interface, providing a comprehensive icon library ([9e9f8b0e2c](https://github.com/dropseed/plain/commit/9e9f8b0e2c))
- Admin lists now support "select all (on all pages)" functionality for bulk operations ([616948c9dd](https://github.com/dropseed/plain/commit/616948c9dd))
- The raw values display feature has been removed from the admin interface ([078f7daeed](https://github.com/dropseed/plain/commit/078f7daeed))
- Description fields have been removed from admin views to simplify the interface ([8baaf1dfcf](https://github.com/dropseed/plain/commit/8baaf1dfcf))
- A copy button has been added to the exception toolbar panel for easier debugging ([8baaf1dfcf](https://github.com/dropseed/plain/commit/8baaf1dfcf))
- New icon element support has been added to the admin interface ([f7e2c9adba](https://github.com/dropseed/plain/commit/f7e2c9adba))
- The admin layout now better accounts for the main app toolbar positioning ([d2b604a699](https://github.com/dropseed/plain/commit/d2b604a699))
- Admin list view display is now a cached_property for improved performance ([095bc93621](https://github.com/dropseed/plain/commit/095bc93621))
- A "back to app" link has been moved to the toolbar when viewing admin pages ([1d17fb5853](https://github.com/dropseed/plain/commit/1d17fb5853))

### Upgrade instructions

- Remove the `description` from any admin views if in use

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
