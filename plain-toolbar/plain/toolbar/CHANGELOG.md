# plain-toolbar changelog

## [0.4.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.4.0) (2025-09-30)

### What's changed

- Renamed `ToolbarPanel` to `ToolbarItem` and `register_toolbar_panel` to `register_toolbar_item` for better clarity ([79654db](https://github.com/dropseed/plain/commit/79654dbefe))
- The toolbar now receives the full template context instead of just the request, allowing toolbar items to access context variables like `object` ([821bfc6](https://github.com/dropseed/plain/commit/821bfc6fab))
- Removed admin URL link from the request panel to reduce clutter ([5e665fd](https://github.com/dropseed/plain/commit/5e665fd4ca))
- Admin link and impersonation UI moved to a new AdminToolbarItem button ([821bfc6](https://github.com/dropseed/plain/commit/821bfc6fab))

### Upgrade instructions

- Replace any usage of `ToolbarPanel` with `ToolbarItem` in your custom toolbar extensions
- Replace any usage of `@register_toolbar_panel` decorator with `@register_toolbar_item`
- Update any custom toolbar items to expect `context` instead of `request` in `__init__()`: change `def __init__(self, request)` to `def __init__(self, context)` and add `self.request = context["request"]`
- The `panel_template_name` attribute replaces `template_name` (though `template_name` still works for backward compatibility)

## [0.3.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.3.0) (2025-09-25)

### What's changed

- Updated toolbar module autodiscovery to use the new `packages_registry.autodiscover_modules()` method ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))

### Upgrade instructions

- No changes required

## [0.2.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.2.0) (2025-09-19)

### What's changed

- Minimum Python version raised to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Upgrade your Python environment to Python 3.13 or later

## [0.1.1](https://github.com/dropseed/plain/releases/plain-toolbar@0.1.1) (2025-08-28)

### What's changed

- Improved null safety when checking user and impersonator attributes in toolbar rendering ([90568bd](https://github.com/dropseed/plain/commit/90568bdfa4))

### Upgrade instructions

- No changes required

## [0.1.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.1.0) (2025-08-27)

### What's changed

- Initial release of plain-toolbar as a standalone package ([e49d54b](https://github.com/dropseed/plain/commit/e49d54bfea162424c73e54bf7ed87e93442af899))
- Fixed URL pattern and name display to include quotes in the request toolbar ([aa759c7](https://github.com/dropseed/plain/commit/aa759c72cae987ed8b6dd07c2e70f5fb97b6fd09))

### Upgrade instructions

- No changes required
