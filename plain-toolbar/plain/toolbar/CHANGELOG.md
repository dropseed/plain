# plain-toolbar changelog

## [0.8.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.8.0) (2025-12-04)

### What's changed

- Exception toolbar now displays rich traceback frames with expandable source code context instead of raw traceback text ([9c4415e](https://github.com/dropseed/plain/commit/9c4415ed6266a36014f1fea75033f3bba4a23b7c))
- Frames are categorized by source (app, plain, plainx, python, third-party) with color-coded badges ([9c4415e](https://github.com/dropseed/plain/commit/9c4415ed6266a36014f1fea75033f3bba4a23b7c))
- App frames are expanded by default while framework/library frames are collapsed ([9c4415e](https://github.com/dropseed/plain/commit/9c4415ed6266a36014f1fea75033f3bba4a23b7c))
- Local variables are displayed for each frame when `DEBUG=True` ([9c4415e](https://github.com/dropseed/plain/commit/9c4415ed6266a36014f1fea75033f3bba4a23b7c))
- Frame filenames link directly to VS Code at the exact line number ([9c4415e](https://github.com/dropseed/plain/commit/9c4415ed6266a36014f1fea75033f3bba4a23b7c))
- Toggle between rich frame view and raw traceback text with the "View raw" button ([9c4415e](https://github.com/dropseed/plain/commit/9c4415ed6266a36014f1fea75033f3bba4a23b7c))

### Upgrade instructions

- No changes required

## [0.7.1](https://github.com/dropseed/plain/releases/plain-toolbar@0.7.1) (2025-10-31)

### What's changed

- The main toolbar script now includes `nonce="{{ request.csp_nonce }}"` for better Content Security Policy compliance ([10f642a](https://github.com/dropseed/plain/commit/10f642a097aa487400f2dffd341f595d93218af9))

### Upgrade instructions

- No changes required

## [0.7.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.7.0) (2025-10-29)

### What's changed

- The toolbar JavaScript now uses CSP-compliant methods by avoiding inline style injection and using CSS classes instead ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd9724c11256cc3aa0a0e15c5c3eae6133c))
- Exception template uses `data-` attributes and event listeners instead of inline `onclick` handlers for better CSP compliance ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd9724c11256cc3aa0a0e15c5c3eae6133c))
- Script tags now include `nonce="{{ request.csp_nonce }}"` to work with Content Security Policy ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd9724c11256cc3aa0a0e15c5c3eae6133c))

### Upgrade instructions

- No changes required

## [0.6.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.6.0) (2025-10-24)

### What's changed

- Added explicit `package_label = "plaintoolbar"` to the package configuration ([d1783dd](https://github.com/dropseed/plain/commit/d1783dd564))

### Upgrade instructions

- No changes required

## [0.5.3](https://github.com/dropseed/plain/releases/plain-toolbar@0.5.3) (2025-10-22)

### What's changed

- Fixed toolbar visibility check to properly use `get_request_impersonator()` helper instead of accessing the `impersonator` attribute directly ([548a385](https://github.com/dropseed/plain/commit/548a385))

### Upgrade instructions

- No changes required

## [0.5.2](https://github.com/dropseed/plain/releases/plain-toolbar@0.5.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations to improve IDE support and type checking ([c87ca27](https://github.com/dropseed/plain/commit/c87ca27ed2))

### Upgrade instructions

- No changes required

## [0.5.1](https://github.com/dropseed/plain/releases/plain-toolbar@0.5.1) (2025-10-02)

### What's changed

- The toolbar now uses `get_request_user()` helper to check user authentication, improving compatibility with different auth implementations ([2663c49](https://github.com/dropseed/plain/commit/2663c49404))

### Upgrade instructions

- No changes required

## [0.5.0](https://github.com/dropseed/plain/releases/plain-toolbar@0.5.0) (2025-09-30)

### What's changed

- The toolbar now uses `settings.VERSION` instead of the deprecated `settings.APP_VERSION` ([4c5f216](https://github.com/dropseed/plain/commit/4c5f2166c1))

### Upgrade instructions

- If you were accessing `settings.APP_VERSION` in any toolbar customizations, update to use `settings.VERSION` instead

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
