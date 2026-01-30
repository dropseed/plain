# plain-admin changelog

## [0.65.1](https://github.com/dropseed/plain/releases/plain-admin@0.65.1) (2026-01-30)

### What's changed

- Fixed `avatar.html` and `img.html` value templates crashing when the field value is `None`, an empty string, or a plain URL string instead of an `Avatar`/`Img` object ([4afb06a6b4](https://github.com/dropseed/plain/commit/4afb06a6b4))

### Upgrade instructions

- No changes required.

## [0.65.0](https://github.com/dropseed/plain/releases/plain-admin@0.65.0) (2026-01-30)

### What's changed

- `format_field_value()` now receives the raw `value` as a third parameter, separating the value retrieval from formatting. Templates now call `get_field_value()` first, then pass the result to `format_field_value()` ([b9b6343f87](https://github.com/dropseed/plain/commit/b9b6343f87))

### Upgrade instructions

- If you override `format_field_value()`, update the method signature to accept the new `value` parameter: `def format_field_value(self, obj, field, value)`. The method should now format and return the provided `value` instead of calling `self.get_field_value()` internally.

## [0.64.0](https://github.com/dropseed/plain/releases/plain-admin@0.64.0) (2026-01-28)

### What's changed

- Added `format_field_value()` method to `AdminListView` and `AdminDetailView` for display-only formatting (e.g. currency symbols, percentages) without affecting sort order or search ([895e94a1b2](https://github.com/dropseed/plain/commit/895e94a1b2))
- Fixed `None` values in column sorting — `None` now always sorts last regardless of sort direction, instead of being coerced to an empty string ([895e94a1b2](https://github.com/dropseed/plain/commit/895e94a1b2))
- Templates now use `format_field_value()` instead of `get_field_value()` for rendering field values in list and detail views ([895e94a1b2](https://github.com/dropseed/plain/commit/895e94a1b2))

### Upgrade instructions

- If you override `get_field_value()` for display formatting, consider moving that logic to `format_field_value()` instead so it doesn't affect sort order.

## [0.63.0](https://github.com/dropseed/plain/releases/plain-admin@0.63.0) (2026-01-28)

### What's changed

- Renamed "presets" to "filters" across list views, templates, and cards. The `presets` attribute is now `filters`, `self.preset` is now `self.filter`, and the `get_presets()` method is now `get_filters()` ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- Renamed `get_objects()` to `get_initial_objects()` as the user-facing hook for providing data, and the internal pipeline method to `process_objects()` ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- Added `filter_objects`/`filter_queryset`, `search_objects`/`search_queryset`, and `order_objects`/`order_queryset` hooks for cleaner overrides in list views ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- Sorting logic moved to base `AdminListView` with smart fallback to in-memory sorting for method/property fields that aren't database columns ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- Non-sortable fields now show a dimmed sort indicator on hover instead of no indicator ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- GET form submissions now exclude empty URL params for cleaner URLs ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- Removed the `show_search` attribute; search is now automatically enabled when `search_fields` is set ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))
- Boolean values (`True`/`False`) now display with green/red label colors for better visual distinction ([9fc78d26e7](https://github.com/dropseed/plain/commit/9fc78d26e7))
- Increased label background opacity from 12% to 25% for better visibility ([9fc78d26e7](https://github.com/dropseed/plain/commit/9fc78d26e7))

### Upgrade instructions

- Rename `presets` to `filters` in your admin viewsets
- Rename `self.preset` to `self.filter` in view methods
- Rename `get_objects()` to `get_initial_objects()` (or use the new `filter_queryset`/`search_queryset`/`order_queryset` hooks for cleaner separation)
- Replace `show_search = True` with `search_fields = [...]`
- Card subclasses: rename `presets` to `filters`, `default_preset` to `default_filter`, `get_current_preset` to `get_current_filter`

## [0.62.1](https://github.com/dropseed/plain/releases/plain-admin@0.62.1) (2026-01-22)

### What's changed

- Admin migrations now use the swappable `AUTH_USER_MODEL` setting instead of hardcoding `users.user`, allowing projects with custom user models to properly reference their user model in the `PinnedNavItem` migration ([76e28f6](https://github.com/dropseed/plain/commit/76e28f6197))

### Upgrade instructions

- No changes required.

## [0.62.0](https://github.com/dropseed/plain/releases/plain-admin@0.62.0) (2026-01-15)

### What's changed

- Mobile support added with responsive navigation, improved menu interactions, and optimized card layouts ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))
- Navigation tabs now visible on mobile with horizontal scrolling and hidden scrollbars ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))
- Menu dialog now includes a close button and closes when clicking the backdrop ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))
- Menu filter input uses 16px font on mobile to prevent iOS auto-zoom ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))
- Cards now use a 2-column grid on mobile with small cards displayed side-by-side ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))
- Datetime values display in condensed format (m/d/yy) on mobile screens ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))
- New `.scrollbar-hide` CSS utility class available for hiding scrollbars while preserving scroll functionality ([ee7acaa](https://github.com/dropseed/plain/commit/ee7acaa67c))

### Upgrade instructions

- No changes required

## [0.61.1](https://github.com/dropseed/plain/releases/plain-admin@0.61.1) (2026-01-15)

### What's changed

- TableCard now supports multiple footer rows by passing a list of lists to `footers`, enabling subtotals and grand totals display ([698e4a8](https://github.com/dropseed/plain/commit/698e4a8811))

### Upgrade instructions

- No changes required

## [0.61.0](https://github.com/dropseed/plain/releases/plain-admin@0.61.0) (2026-01-15)

### What's changed

- Complete admin interface redesign with new color palette, improved typography, and modern styling ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- New pinned navigation system that lets users pin frequently-used pages to the header for quick access ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Recently visited pages now appear as tabs in the header navigation ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- New menu dialog with filtering for quick access to any admin page ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- New `/admin/style/` page documenting the design system with CSS variables, component patterns, and usage examples ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Card `number` field renamed to `metric` with new `get_metric()` and `format_metric()` methods for custom formatting ([1a1c622](https://github.com/dropseed/plain/commit/1a1c622539))
- Field labels in list and detail views now display human-readable names (e.g., `created_at` → "Created At") ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Boolean values now display as "True"/"False" labels instead of checkmark/X icons ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Datetime values now display in a friendlier format (e.g., "Jan 15, 2026 at 4:30 PM") ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Empty states added to list views when there are no results ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Charts now display an empty state when there's no data for the selected period ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Form required fields now show a red asterisk instead of "Optional" label on optional fields ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Delete confirmation page redesigned with clearer messaging and cancel option ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Model update URL path changed from `/update/` to `/edit/` ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- New CSS classes available: `.plain-btn`, `.plain-btn-primary`, `.plain-btn-danger`, `.plain-btn-success`, `.plain-btn-warning`, `.plain-label`, `.plain-label-success`, `.plain-label-warning`, `.plain-label-danger`, `.plain-label-info`, `.plain-link`, `.plain-error`, `.card` ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- New avatar template value type for circular profile images ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))
- Admin `description` attribute restored for showing subtitle text below page titles ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))

### Upgrade instructions

- Run migrations with `plain migrate` to create the new `PinnedNavItem` model for navigation pins
- If you have custom Card subclasses that override `get_number()`, rename it to `get_metric()`. The return type can now be `int | float | Decimal | None`
- If you want custom metric display formatting, override `format_metric()` which returns a string
- If you have hardcoded links to admin update pages ending in `/update/`, update them to `/edit/`
- The sidebar has been removed; if you have custom CSS targeting sidebar elements, those styles can be removed

## [0.60.0](https://github.com/dropseed/plain/releases/plain-admin@0.60.0) (2026-01-13)

### What's changed

- README documentation expanded with comprehensive examples for viewsets, cards, forms, actions, toolbar, and impersonation ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.59.0](https://github.com/dropseed/plain/releases/plain-admin@0.59.0) (2026-01-13)

### What's changed

- Internal response classes updated to use the new naming convention: `ResponseRedirect` → `RedirectResponse` ([fad5bf2](https://github.com/dropseed/plain/commit/fad5bf28b0))

### Upgrade instructions

- No changes required

## [0.58.0](https://github.com/dropseed/plain/releases/plain-admin@0.58.0) (2025-12-26)

### What's changed

- Admin page titles for model views now properly convert CamelCase model names to readable titles (e.g., "URLParser" becomes "URL parser", "ThisThing" becomes "This thing") ([c153390](https://github.com/dropseed/plain/commit/c153390f26))

### Upgrade instructions

- No changes required

## [0.57.2](https://github.com/dropseed/plain/releases/plain-admin@0.57.2) (2025-12-22)

### What's changed

- Internal type annotation cleanup for improved type checker compatibility ([539a706](https://github.com/dropseed/plain/commit/539a706760))

### Upgrade instructions

- No changes required

## [0.57.1](https://github.com/dropseed/plain/releases/plain-admin@0.57.1) (2025-12-05)

### What's changed

- Select dropdowns now hide the browser's default arrow for a cleaner appearance ([709b8d2](https://github.com/dropseed/plain/commit/709b8d2d27))

### Upgrade instructions

- No changes required

## [0.57.0](https://github.com/dropseed/plain/releases/plain-admin@0.57.0) (2025-12-04)

### What's changed

- Internal type annotation improvements for better IDE support and type checking ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.56.0](https://github.com/dropseed/plain/releases/plain-admin@0.56.0) (2025-11-24)

### What's changed

- Admin views now use `request.form_data` instead of `request.data` for processing form submissions, following the new request data API ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- View mixins (`AuthViewMixin`, `HTMXViewMixin`, `SessionViewMixin`) have been replaced with view inheritance (`AuthView`, `HTMXView`, `SessionView`) for better type checking support ([569afd6](https://github.com/dropseed/plain/commit/569afd606d))
- Type annotations have been improved throughout admin views, including `form_class`, model types, and response types ([793c57b](https://github.com/dropseed/plain/commit/793c57b200), [3c3a984](https://github.com/dropseed/plain/commit/3c3a984428), [0466ee2](https://github.com/dropseed/plain/commit/0466ee2f74))

### Upgrade instructions

- No changes required

## [0.55.0](https://github.com/dropseed/plain/releases/plain-admin@0.55.0) (2025-11-14)

### What's changed

- Date range dropdowns now correctly compare enum values instead of enum instances when resolving aliases ([3b49eb0](https://github.com/dropseed/plain/commit/3b49eb0258))

### Upgrade instructions

- No changes required

## [0.54.0](https://github.com/dropseed/plain/releases/plain-admin@0.54.0) (2025-11-12)

### What's changed

- `ChartCard` is now an abstract base class with `get_chart_data()` as an abstract method ([81489a6](https://github.com/dropseed/plain/commit/81489a6e50))
- Type annotations have been improved throughout the package, including better type checking for `DatetimeRange`, card presets, and model list view querysets ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa92))
- Admin model list views no longer fall back to Python-based sorting when an invalid field is used in `order_by` - instead, `FieldError` will propagate to surface the issue ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa92))

### Upgrade instructions

- No changes required

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
