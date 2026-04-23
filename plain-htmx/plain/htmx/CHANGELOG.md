# plain-htmx changelog

## [0.18.3](https://github.com/dropseed/plain/releases/plain-htmx@0.18.3) (2026-04-23)

### What's changed

- `HTMXView.after_response` annotates against `Response` after plain 0.135.0 merged `ResponseBase` into `Response`. ([f5007281d7fa](https://github.com/dropseed/plain/commit/f5007281d7fa))

### Upgrade instructions

- Requires `plain>=0.135.0`.

## [0.18.2](https://github.com/dropseed/plain/releases/plain-htmx@0.18.2) (2026-04-21)

### What's changed

- Migrated `HTMXView` to the new `View.after_response` hook for the `Vary` header patch (`Plain-HX-Action`, `Plain-HX-Fragment`). ([0da5639d17e2](https://github.com/dropseed/plain/commit/0da5639d17e2), [48effac976a9](https://github.com/dropseed/plain/commit/48effac976a9))
- `get_request_handler()` now validates the request method against `http.HTTPMethod` and requires the `Plain-HX-Action` value to be a valid Python identifier before dispatching to `htmx_{method}_{action}`. Invalid methods or non-identifier actions fall through to 405 instead of raising. ([5da708a057db](https://github.com/dropseed/plain/commit/5da708a057db))

### Upgrade instructions

- Requires `plain>=0.133.0`.

## [0.18.1](https://github.com/dropseed/plain/releases/plain-htmx@0.18.1) (2026-04-01)

### What's changed

- Added Claude agent rule with HTMX view dispatching patterns and `plain request` testing examples. ([c80596b71cf9](https://github.com/dropseed/plain/commit/c80596b71cf9))

### Upgrade instructions

- No changes required.

## [0.18.0](https://github.com/dropseed/plain/releases/plain-htmx@0.18.0) (2026-03-20)

### What's changed

- `{% htmxfragment %}` now supports dynamic fragment names (e.g., `"item-" ~ item.pk`), enabling use inside `{% for %}` loops where each iteration gets a unique fragment name ([6ddaa13845](https://github.com/dropseed/plain/commit/6ddaa13845))
- Rewrote fragment rendering to use a two-phase runtime approach instead of static template-tree walking, which is what enables dynamic and loop-based fragments ([6ddaa13845](https://github.com/dropseed/plain/commit/6ddaa13845))
- Lazy fragments now default to `hx-trigger="load from:body"` ([6ddaa13845](https://github.com/dropseed/plain/commit/6ddaa13845))

### Upgrade instructions

- No changes required. Existing static fragment names continue to work as before. To use fragments in loops, pass a dynamic expression as the fragment name (e.g., `{% htmxfragment "item-" ~ item.pk %}`).

## [0.17.1](https://github.com/dropseed/plain/releases/plain-htmx@0.17.1) (2026-03-10)

### What's changed

- Fixed `CallBlock.set_lineno()` return value assumption — `set_lineno` returns `None`, so the node is now assigned before calling it ([cda461b1b4f6](https://github.com/dropseed/plain/commit/cda461b1b4f6))
- Added `None` check for template references in fragment discovery to prevent `TypeError` ([cda461b1b4f6](https://github.com/dropseed/plain/commit/cda461b1b4f6))

### Upgrade instructions

- No changes required.

## [0.17.0](https://github.com/dropseed/plain/releases/plain-htmx@0.17.0) (2026-03-07)

### What's changed

- Updated README example to use keyword arguments in `url()` calls instead of positional arguments (e.g., `url('pullrequests:detail', uuid=pullrequest.uuid)` instead of `url('pullrequests:detail', pullrequest.uuid)`) ([6eecc35](https://github.com/dropseed/plain/commit/6eecc35ff197))

### Upgrade instructions

- Update any `url()` calls in templates that use positional arguments to use keyword arguments instead.

## [0.16.2](https://github.com/dropseed/plain/releases/plain-htmx@0.16.2) (2026-02-26)

### What's changed

- Auto-formatted JavaScript assets and config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.16.1](https://github.com/dropseed/plain/releases/plain-htmx@0.16.1) (2026-02-04)

### What's changed

- Added `__all__` export to `views` module for explicit public API boundaries ([f26a63a5c941](https://github.com/dropseed/plain/commit/f26a63a5c941))

### Upgrade instructions

- No changes required.

## [0.16.0](https://github.com/dropseed/plain/releases/plain-htmx@0.16.0) (2026-01-13)

### What's changed

- Improved README documentation with better structure, examples, and FAQs section ([da37a78](https://github.com/dropseed/plain/commit/da37a78))

### Upgrade instructions

- No changes required

## [0.15.1](https://github.com/dropseed/plain/releases/plain-htmx@0.15.1) (2025-12-22)

### What's changed

- Internal code cleanup to remove unnecessary type ignore comments ([539a706](https://github.com/dropseed/plain/commit/539a706))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-htmx@0.15.0) (2025-12-09)

### What's changed

- Native browser form validation is now enabled by default via `htmx.config.reportValidityOfForms`, so forms with HTML5 validation attributes will show validation feedback before submitting ([b9e2476](https://github.com/dropseed/plain/commit/b9e2476))

### Upgrade instructions

- Test your usage of HTMX forms where client validation is concerned

## [0.14.0](https://github.com/dropseed/plain/releases/plain-htmx@0.14.0) (2025-12-04)

### What's changed

- Improved type annotations for template extension context handling ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-htmx@0.13.0) (2025-11-24)

### What's changed

- Replaced `HTMXViewMixin` with `HTMXView` class that inherits from `TemplateView` for better type checking support ([569afd6](https://github.com/dropseed/plain/commit/569afd6))

### Upgrade instructions

- Replace `class MyView(HTMXViewMixin, TemplateView)` with `class MyView(HTMXView)` - the new `HTMXView` class already inherits from `TemplateView`
- Update imports from `from plain.htmx.views import HTMXViewMixin` to `from plain.htmx.views import HTMXView`

## [0.12.0](https://github.com/dropseed/plain/releases/plain-htmx@0.12.0) (2025-11-12)

### What's changed

- Improved type checking compatibility by adding type ignore comments for mixin methods and ensuring proper None handling ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcef))

### Upgrade instructions

- No changes required

## [0.11.1](https://github.com/dropseed/plain/releases/plain-htmx@0.11.1) (2025-10-31)

### What's changed

- Added CSP nonce support to all htmx script tags for improved Content Security Policy compatibility ([10f642a](https://github.com/dropseed/plain/commit/10f642a097))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-htmx@0.11.0) (2025-10-29)

### What's changed

- Added Content Security Policy (CSP) nonce support for inline scripts and styles generated by htmx ([784f3dd](https://github.com/dropseed/plain/commit/784f3dd972))

### Upgrade instructions

- No changes required

## [0.10.4](https://github.com/dropseed/plain/releases/plain-htmx@0.10.4) (2025-10-20)

### What's changed

- Updated package configuration to use `dependency-groups.dev` instead of `tool.uv.dev-dependencies` ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.10.3](https://github.com/dropseed/plain/releases/plain-htmx@0.10.3) (2025-10-06)

### What's changed

- Added type annotations for improved IDE and type checker support ([8cdda13](https://github.com/dropseed/plain/commit/8cdda13a6c))

### Upgrade instructions

- No changes required

## [0.10.2](https://github.com/dropseed/plain/releases/plain-htmx@0.10.2) (2025-10-02)

### What's changed

- Fixed documentation examples to use `self.user` instead of `self.request.user` ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.10.1](https://github.com/dropseed/plain/releases/plain-htmx@0.10.1) (2025-09-09)

### What's changed

- Fixed documentation examples to remove unnecessary `self.object = self.get_object()` calls in HTMX action methods ([aa67cae](https://github.com/dropseed/plain/commit/aa67cae65c))
- Updated minimum Python version requirement to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- No changes required

## [0.10.0](https://github.com/dropseed/plain/releases/plain-htmx@0.10.0) (2025-08-19)

### What's changed

- CSRF tokens are now handled automatically using `Sec-Fetch-Site` headers instead of requiring manual token management ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- Updated README with improved structure, table of contents, and better installation instructions ([4ebecd1856](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.9.2](https://github.com/dropseed/plain/releases/plain-htmx@0.9.2) (2025-07-21)

### What's changed

- Fixed documentation examples to properly quote htmxfragment template tag names ([8e4f6d8](https://github.com/dropseed/plain/commit/8e4f6d889e))

### Upgrade instructions

- No changes required

## [0.9.1](https://github.com/dropseed/plain/releases/plain-htmx@0.9.1) (2025-06-26)

### What's changed

- Added a new `CHANGELOG.md` file so future changes are easier to follow ([82710c3](https://github.com/dropseed/plain/commit/82710c3c83)).

### Upgrade instructions

- No changes required
