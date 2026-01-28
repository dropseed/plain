# plain-pages changelog

## [0.18.1](https://github.com/dropseed/plain/releases/plain-pages@0.18.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.18.0](https://github.com/dropseed/plain/releases/plain-pages@0.18.0) (2026-01-13)

### What's changed

- Improved README documentation with FAQs section and clearer structure ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-pages@0.17.0) (2026-01-13)

### What's changed

- Updated to use renamed HTTP exception `NotFoundError404` (previously `Http404`) ([5a1f020](https://github.com/dropseed/plain/commit/5a1f020f52))
- Updated to use renamed response class `RedirectResponse` (previously `ResponseRedirect`) ([fad5bf2](https://github.com/dropseed/plain/commit/fad5bf28b0))

### Upgrade instructions

- No changes required

## [0.16.1](https://github.com/dropseed/plain/releases/plain-pages@0.16.1) (2025-12-22)

### What's changed

- Updated type ignore comments for improved type checker compatibility ([539a706](https://github.com/dropseed/plain/commit/539a706))

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-pages@0.16.0) (2025-11-12)

### What's changed

- Improved type checking compatibility with updated type checker ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcef))

### Upgrade instructions

- No changes required

## [0.15.1](https://github.com/dropseed/plain/releases/plain-pages@0.15.1) (2025-10-31)

### What's changed

- Added license metadata to `pyproject.toml` for better package distribution ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-pages@0.15.0) (2025-10-24)

### What's changed

- Added explicit package label `plainpages` for better package identification and CLI integration ([d1783dd](https://github.com/dropseed/plain/commit/d1783dd564))

### Upgrade instructions

- No changes required

## [0.14.2](https://github.com/dropseed/plain/releases/plain-pages@0.14.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package for improved type checking and IDE support ([c87ca27](https://github.com/dropseed/plain/commit/c87ca27ed2))

### Upgrade instructions

- No changes required

## [0.14.1](https://github.com/dropseed/plain/releases/plain-pages@0.14.1) (2025-10-02)

### What's changed

- Fixed documentation example to use `get_current_user()` instead of `request.user` ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-pages@0.14.0) (2025-09-30)

### What's changed

- Pages now support content negotiation via Accept headers to serve raw markdown when `PAGES_SERVE_MARKDOWN` is enabled ([b105ba4](https://github.com/dropseed/plain/commit/b105ba4dd0))
- Renamed `PAGES_MARKDOWN_URLS` setting to `PAGES_SERVE_MARKDOWN` for clarity ([b105ba4](https://github.com/dropseed/plain/commit/b105ba4dd0))

### Upgrade instructions

- If you were using `PAGES_MARKDOWN_URLS = True` in your settings, rename it to `PAGES_SERVE_MARKDOWN = True`

## [0.13.0](https://github.com/dropseed/plain/releases/plain-pages@0.13.0) (2025-09-19)

### What's changed

- Updated minimum Python requirement from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Update your Python environment to version 3.13 or higher

## [0.12.2](https://github.com/dropseed/plain/releases/plain-pages@0.12.2) (2025-08-22)

### What's changed

- Enhanced markdown URL resolving to preserve query parameters and fragments when converting relative links to page URLs ([545b406](https://github.com/dropseed/plain/commit/545b406a22))

### Upgrade instructions

- No changes required

## [0.12.1](https://github.com/dropseed/plain/releases/plain-pages@0.12.1) (2025-08-15)

### What's changed

- Improved relative markdown link conversion to handle links that don't use `./` or `../` prefixes, automatically converting plain filenames and paths to proper page URLs ([f98416e](https://github.com/dropseed/plain/commit/f98416e1e7))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-pages@0.12.0) (2025-08-15)

### What's changed

- Redirect pages now use a `status_code` variable instead of the boolean `temporary` variable for greater control over redirect status codes ([ba79ce3](https://github.com/dropseed/plain/commit/ba79ce3d70))
- Removed dependency on `ResponsePermanentRedirect` in favor of using `status_code` parameter in `ResponseRedirect` ([d5735ea](https://github.com/dropseed/plain/commit/d5735ea4f8))

### Upgrade instructions

- Replace any `temporary: false` variables in redirect pages with `status_code: 301` for permanent redirects
- Replace any `temporary: true` variables in redirect pages with `status_code: 302` for temporary redirects (or simply remove the variable as 302 is now the default)

## [0.11.0](https://github.com/dropseed/plain/releases/plain-pages@0.11.0) (2025-08-15)

### What's changed

- Added raw markdown serving feature that allows markdown files to be served at `.md` URLs alongside rendered HTML pages ([b13a544](https://github.com/dropseed/plain/commit/b13a544679c5ffc172fb3e0ef53b97a2a6c50ccb))
- Automatic markdown relative link conversion that resolves `./` and `../` links in markdown to proper page URLs ([b13a544](https://github.com/dropseed/plain/commit/b13a544679c5ffc172fb3e0ef53b97a2a6c50ccb))
- Added `get_markdown_url()` method to pages for linking to raw markdown content ([b13a544](https://github.com/dropseed/plain/commit/b13a544679c5ffc172fb3e0ef53b97a2a6c50ccb))

### Upgrade instructions

- No changes required

## [0.10.5](https://github.com/dropseed/plain/releases/plain-pages@0.10.5) (2025-07-31)

### What's changed

- Support for symlinks when discovering pages in templates/pages directories ([c5e610d](https://github.com/dropseed/plain/commit/c5e610dfb7161551efdc82a23dac985e89078059))
- Updated package description and comprehensive README documentation ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- No changes required

## [0.10.4](https://github.com/dropseed/plain/releases/plain-pages@0.10.4) (2025-06-23)

### What's changed

- No user-facing changes. This release only updates internal project metadata and documentation.

### Upgrade instructions

- No changes required.
