# plain-htmx changelog

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
