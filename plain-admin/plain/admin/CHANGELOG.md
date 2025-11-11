# plain-admin changelog

## [0.53.2](https://github.com/dropseed/plain/releases/plain-admin@0.53.2) (2025-11-11)

### What's changed

- Internal import path updated to use `plain.models.aggregates.Count` instead of importing from `plain.models` directly ([e9edf61](https://github.com/dropseed/plain/commit/e9edf61c6b))

### Upgrade instructions

- No changes required

## [0.53.1](https://github.com/dropseed/plain/releases/plain-admin@0.53.1) (2025-10-31)

### What's changed

- Dependency updates for `plain-auth` (0.20.7) and `plain-htmx` (0.11.0)

### Upgrade instructions

- No changes required

## [0.53.0](https://github.com/dropseed/plain/releases/plain-admin@0.53.0) (2025-10-29)

### What's changed

- Admin templates now support Content Security Policy (CSP) nonces by using `request.csp_nonce` on inline script tags ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Tippy.js library has been split into separate CSS and JavaScript files instead of using a bundle, improving CSP compatibility ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Chart rendering now includes null checks to prevent errors when chart elements don't exist on the page ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))
- Card template context now includes the request object for accessing request-scoped data like CSP nonces ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))

### Upgrade instructions

- No changes required

## [0.52.2](https://github.com/dropseed/plain/releases/plain-admin@0.52.2) (2025-10-27)

### What's changed

- Action buttons reverted to stone-100 background with stone-300 border for improved visual consistency ([a612370](https://github.com/dropseed/plain/commit/a612370b33))

### Upgrade instructions

- No changes required

## [0.52.1](https://github.com/dropseed/plain/releases/plain-admin@0.52.1) (2025-10-27)

### What's changed

- Admin sidebar now uses `data-sidebar-collapsed` attribute instead of a CSS class for better compatibility with Tailwind's arbitrary variant syntax ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))
- Admin layout updated with improved visual design including rounded content area with subtle border, refined spacing, and cleaner background colors ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))
- Table headers now have a subtle background color (stone-50) for better visual hierarchy ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))
- Action buttons updated with lighter default styling using white background instead of stone-100 ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))
- Sidebar preview overlay now uses backdrop blur effect for a more modern appearance ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))
- Top bar search input now includes subtle inset shadow for better depth perception ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))
- List view footer now only displays when pagination is needed ([d6fc253](https://github.com/dropseed/plain/commit/d6fc2537df))

### Upgrade instructions

- No changes required

## [0.52.0](https://github.com/dropseed/plain/releases/plain-admin@0.52.0) (2025-10-24)

### What's changed

- Admin list and card "displays" have been renamed to "presets" for better clarity ([0ecc60f](https://github.com/dropseed/plain/commit/0ecc60f19e5cf7db10a7d05e5a799d001725d1fc))
- Model choice fields now use the newer `get_field_display()` method directly instead of relying on a separate template ([1d78191](https://github.com/dropseed/plain/commit/1d781919be7c4b8f6390faeac9df596934f7e760))
- Added `is_package_installed()` template function for checking if a package is installed in templates ([4362649](https://github.com/dropseed/plain/commit/43626494a275631ee1ee0d6fa8b4597c7e998fc1))
- Changed default navigation icon from chevron to dot for a cleaner appearance ([b6a588a](https://github.com/dropseed/plain/commit/b6a588a598f54b818530fed4b736dda1a88f2353))
- Fixed impersonation toolbar item to properly include user context ([92ba1cf](https://github.com/dropseed/plain/commit/92ba1cfd4ce377be54942d530f2c37f68bf4851a))
- Fixed CSS ring styling on admin select elements ([80d7243](https://github.com/dropseed/plain/commit/80d7243cede69b290421618e08ffb82f4f6b15cc))
- Admin interface now includes a lighter, more modern visual design with improved styling and layout ([daadf1a](https://github.com/dropseed/plain/commit/daadf1a53d6f86ea6643d938ccb4d348e124efd8))
- Chart card styling has been simplified and improved ([88cabeb](https://github.com/dropseed/plain/commit/88cabeb887209a63ef5d2885bc7a7d250ca3b44a))

### Upgrade instructions

- Update any admin list views or cards that use the `displays` attribute to use `presets` instead
- Update any custom templates that reference the `display` query parameter to use `preset` instead
- Update any custom templates that reference `get_displays()` method to use `get_presets()` instead
- Remove the `admin/values/get_display.html` template if you have customized it (choice field display is now handled automatically)

## [0.51.0](https://github.com/dropseed/plain/releases/plain-admin@0.51.0) (2025-10-22)

### What's changed

- Admin middleware classes now inherit from the new `HttpMiddleware` abstract base class, using the standardized `process_request()` method instead of `__call__()` ([b960eed](https://github.com/dropseed/plain/commit/b960eed6c6))

### Upgrade instructions

- No changes required

## [0.50.2](https://github.com/dropseed/plain/releases/plain-admin@0.50.2) (2025-10-20)

### What's changed

- Internal build system update to use dependency-groups.dev format ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.50.1](https://github.com/dropseed/plain/releases/plain-admin@0.50.1) (2025-10-17)

### What's changed

- Fixed the "View results" link from global search to properly include search query parameters and use the correct path ([99a43ed](https://github.com/dropseed/plain/commit/99a43ed6d9))

### Upgrade instructions

- No changes required

## [0.50.0](https://github.com/dropseed/plain/releases/plain-admin@0.50.0) (2025-10-07)

### What's changed

- Admin model views now use `model.model_options` instead of `model._meta` for accessing model metadata like `model_name` ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))
- Admin model detail views now use `object._model_meta` instead of `object._meta` for accessing field metadata ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.49.1](https://github.com/dropseed/plain/releases/plain-admin@0.49.1) (2025-10-06)

### What's changed

- Type annotations have been added throughout the admin package, improving IDE support and type checking ([53b69d7](https://github.com/dropseed/plain/commit/53b69d7e08))

### Upgrade instructions

- No changes required

## [0.49.0](https://github.com/dropseed/plain/releases/plain-admin@0.49.0) (2025-10-02)

### What's changed

- Impersonation now uses a request-scoped storage pattern instead of request attributes, making it compatible with middleware that doesn't use `plain.auth.middleware.AuthenticationMiddleware` ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- Added `get_request_impersonator()` helper function to safely retrieve the impersonator from any request context ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- The admin toolbar now uses the new request helpers to display impersonation status correctly ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- If you were accessing `request.impersonator` directly in your code, update to use `from plain.admin.impersonate import get_request_impersonator` and call `get_request_impersonator(request)` instead

## [0.48.0](https://github.com/dropseed/plain/releases/plain-admin@0.48.0) (2025-09-30)

### What's changed

- The `HttpRequest` class has been renamed to `Request` throughout the codebase for better consistency and brevity ([cd46ff2](https://github.com/dropseed/plain/commit/cd46ff2003))
- Admin views now use the renamed `settings.NAME` instead of `settings.APP_NAME` following the global settings refactor ([4c5f216](https://github.com/dropseed/plain/commit/4c5f2166c1))

### Upgrade instructions

- If you have custom admin views or cards that reference `HttpRequest`, update them to use `Request` instead
- If you're accessing `settings.APP_NAME` in admin customizations, update to use `settings.NAME`

## [0.47.0](https://github.com/dropseed/plain/releases/plain-admin@0.47.0) (2025-09-30)

### What's changed

- Added a new admin toolbar item that integrates with the plain-toolbar package, providing quick admin access and navigation ([79654db](https://github.com/dropseed/plain/commit/79654dbefe))
- The toolbar now shows direct links to admin pages for objects when viewing non-admin pages that have a corresponding admin detail view ([821bfc6](https://github.com/dropseed/plain/commit/821bfc6fab))
- Removed the `is_admin_view` context variable from admin views as it was no longer needed ([79654db](https://github.com/dropseed/plain/commit/79654dbefe))

### Upgrade instructions

- No changes required

## [0.46.0](https://github.com/dropseed/plain/releases/plain-admin@0.46.0) (2025-09-30)

### What's changed

- Type annotations have been added throughout the admin views module, improving IDE support and type checking for better developer experience ([5bf1192](https://github.com/dropseed/plain/commit/5bf11926c7), [365414c](https://github.com/dropseed/plain/commit/365414cc6f))

### Upgrade instructions

- No changes required

## [0.45.0](https://github.com/dropseed/plain/releases/plain-admin@0.45.0) (2025-09-29)

### What's changed

- Import path for `FieldError` exception updated to use `plain.models.exceptions` following the reorganization of exception classes ([1c02564](https://github.com/dropseed/plain/commit/1c02564561))

### Upgrade instructions

- No changes required

## [0.44.1](https://github.com/dropseed/plain/releases/plain-admin@0.44.1) (2025-09-25)

### What's changed

- Fixed admin card col-span class detection for Tailwind CSS by using explicit class names instead of dynamic string interpolation ([7a7a394](https://github.com/dropseed/plain/commit/7a7a394e8e))

### Upgrade instructions

- No changes required

## [0.44.0](https://github.com/dropseed/plain/releases/plain-admin@0.44.0) (2025-09-25)

### What's changed

- Admin module autodiscovery now uses the new `packages_registry.autodiscover_modules()` API for cleaner and more consistent module loading ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))

### Upgrade instructions

- No changes required

## [0.43.0](https://github.com/dropseed/plain/releases/plain-admin@0.43.0) (2025-09-12)

### What's changed

- Related manager handling has been improved to use the updated `BaseRelatedManager` interface from plain-models refactoring ([9f0b039](https://github.com/dropseed/plain/commit/9f0b03957a6f103b93c9b44f0e7861596f4d2efa))

### Upgrade instructions

- No changes required

## [0.42.0](https://github.com/dropseed/plain/releases/plain-admin@0.42.0) (2025-09-12)

### What's changed

- Model manager access has been renamed from `.objects` to `.query` throughout the admin interface ([037a239](https://github.com/dropseed/plain/commit/037a239ef4711c4477a211d63c57ad8414096301))
- Related manager objects are now returned as QuerySet instances instead of Manager instances in admin model field processing ([bbaee93](https://github.com/dropseed/plain/commit/bbaee93839c731d2b1308981c1aac6c9d62a12a3))

### Upgrade instructions

- No changes required

## [0.41.1](https://github.com/dropseed/plain/releases/plain-admin@0.41.1) (2025-09-09)

### What's changed

- Admin list columns now truncate at a maximum width with proper text overflow handling for better readability on wide tables ([c0b8eab](https://github.com/dropseed/plain/commit/c0b8eabc29a5cffa8e2d7aaa1c90fe6c82fdc52b))
- Fixed extra spacing at the bottom of admin pages from the old toolbar implementation ([d2c2c65](https://github.com/dropseed/plain/commit/d2c2c65ffe4fece15f01bab8b32eeaffacc37b1b))

### Upgrade instructions

- No changes required

## [0.41.0](https://github.com/dropseed/plain/releases/plain-admin@0.41.0) (2025-08-27)

### What's changed

- Admin toolbar functionality has been moved to the new `plain-toolbar` package, separating concerns and allowing the toolbar to be used independently ([e49d54bf](https://github.com/dropseed/plain/commit/e49d54bfea162424c73e54bf7ed87e93442af899))
- The `ADMIN_TOOLBAR_VERSION` setting has been replaced with the new global `APP_VERSION` setting ([57fb948d](https://github.com/dropseed/plain/commit/57fb948d465789a08c60b68ff71aa7edd671a571))
- The `ADMIN_TOOLBAR_CLASS` setting has been removed in favor of direct toolbar class usage ([f6d8162c](https://github.com/dropseed/plain/commit/f6d8162c5bbc19172a8a4284b047251738f741c1))

### Upgrade instructions

- Install the new `plain-toolbar` package as a dependency: `uv add plain-toolbar`
- Add `"plain.toolbar"` to your `INSTALLED_PACKAGES`
- The `ADMIN_TOOLBAR_CLASS` setting has been removed
- The `ADMIN_TOOLBAR_VERSION` setting has been replaced by `APP_VERSION`
- Toolbar customizations should move from any `admin.py` files to `toolbar.py` files

## [0.40.0](https://github.com/dropseed/plain/releases/plain-admin@0.40.0) (2025-08-22)

### What's changed

- Navigation icons are now displayed on section headers instead of individual items, improving visual hierarchy and navigation organization ([5a6479ac79](https://github.com/dropseed/plain/commit/5a6479ac79b2a082a5d29a0b8cb0385401bad63b))
- Admin interface now uses the configured `APP_NAME` setting instead of hard-coded "Plain" in titles and branding ([762c092652](https://github.com/dropseed/plain/commit/762c092652d53aa7922d03a3fcfb0d74a19ab8bd))
- User avatars now display Gravatar images when available, falling back to the default person icon for users without email addresses ([b1303acf52](https://github.com/dropseed/plain/commit/b1303acf52934c121ec5390a050c192b55152a95))
- Navigation sections now use accordion-style behavior, automatically closing other sections when one is opened ([5a6479ac79](https://github.com/dropseed/plain/commit/5a6479ac79b2a082a5d29a0b8cb0385401bad63b))
- The toolbar "Back to app" link now dynamically shows the configured app name instead of a generic label ([b1303acf52](https://github.com/dropseed/plain/commit/b1303acf52934c121ec5390a050c192b55152a95))

### Upgrade instructions

- No changes required

## [0.39.0](https://github.com/dropseed/plain/releases/plain-admin@0.39.0) (2025-08-19)

### What's changed

- CSRF protection has been improved to use Sec-Fetch-Site headers instead of manual token inputs in admin templates ([955150800c](https://github.com/dropseed/plain/commit/955150800c9ca9c7d00d27e9b2d0688aed252fad))
- Manual `{{ csrf_input }}` tokens have been removed from admin delete and list action forms as they are no longer needed ([955150800c](https://github.com/dropseed/plain/commit/955150800c9ca9c7d00d27e9b2d0688aed252fad))

### Upgrade instructions

- No changes required

## [0.38.1](https://github.com/dropseed/plain/releases/plain-admin@0.38.1) (2025-07-30)

### What's changed

- Ungrouped admin items are now displayed at the top of the navigation sidebar for better organization ([0e04d5a](https://github.com/dropseed/plain/commit/0e04d5a33aa7ab5e9dfb7dcd3dd525a0b2a748ec))
- Navigation styling improvements including cursor pointer on collapsible sections, better spacing, and text truncation for long titles ([0e04d5a](https://github.com/dropseed/plain/commit/0e04d5a33aa7ab5e9dfb7dcd3dd525a0b2a748ec))

### Upgrade instructions

- No changes required

## [0.38.0](https://github.com/dropseed/plain/releases/plain-admin@0.38.0) (2025-07-30)

### What's changed

- Navigation sidebar now uses app-only sections, hiding plain package views for a cleaner interface ([bfdc928](https://github.com/dropseed/plain/commit/bfdc928fe448174a4cafc5eac26f63193a705059))
- Added HTMX navigation with collapsible sections and active state tracking ([bfdc928](https://github.com/dropseed/plain/commit/bfdc928fe448174a4cafc5eac26f63193a705059))
- Updated jQuery from 3.6.1 to 3.7.1 for improved compatibility and security ([bfdc928](https://github.com/dropseed/plain/commit/bfdc928fe448174a4cafc5eac26f63193a705059))
- Exception display in toolbar now shows exception message on its own line for better readability ([fe10d45](https://github.com/dropseed/plain/commit/fe10d45669557551c4a547172ed0fe2d81614b74))
- Admin sidebar now preserves state during HTMX navigation with `hx-preserve="true"` ([bfdc928](https://github.com/dropseed/plain/commit/bfdc928fe448174a4cafc5eac26f63193a705059))

### Upgrade instructions

- No changes required

## [0.37.3](https://github.com/dropseed/plain/releases/plain-admin@0.37.3) (2025-07-30)

### What's changed

- Fixed duplicate plainToolbar JavaScript objects that could occur on pages with multiple toolbar inclusions ([1747ca6](https://github.com/dropseed/plain/commit/1747ca6fa758d5176c0ab770177130ac5497cf29))
- Improved README documentation with better structure and table of contents ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- No changes required

## [0.37.2](https://github.com/dropseed/plain/releases/plain-admin@0.37.2) (2025-07-25)

### What's changed

- No user-facing changes in this release

### Upgrade instructions

- No changes required

## [0.37.1](https://github.com/dropseed/plain/releases/plain-admin@0.37.1) (2025-07-25)

### What's changed

- Fixed breadcrumbs navigation in detail views to properly handle object context and URL generation ([38c9f12](https://github.com/dropseed/plain/commit/38c9f12ed473782b5edcbc79e52735513e6009d2))

### Upgrade instructions

- No changes required

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
