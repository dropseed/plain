# plain-email changelog

## [0.13.0](https://github.com/dropseed/plain/releases/plain-email@0.13.0) (2025-12-04)

### What's changed

- Internal typing improvements for better type checker compatibility ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea05b26dfc7e32c50f2a5a5bc7e098ceb))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-email@0.12.0) (2025-11-12)

### What's changed

- The filebased email backend now requires `EMAIL_FILE_PATH` to be set and raises `ImproperlyConfigured` if not provided ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa929058be517cb1d4ab35bd73a89f26b8))
- `BaseEmailBackend` now uses Python's abstract base class with `@abstractmethod` for better type checking ([245b5f4](https://github.com/dropseed/plain/commit/245b5f472c89178b8b764869f1624f8fc885b0f7))

### Upgrade instructions

- If using the filebased email backend, ensure `EMAIL_FILE_PATH` is configured in your settings or passed when initializing the backend

## [0.11.1](https://github.com/dropseed/plain/releases/plain-email@0.11.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package for improved IDE support and type checking ([5a32120](https://github.com/dropseed/plain/commit/5a3212020c473d3a10763cedd0b0b7ca778911de))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-email@0.11.0) (2025-09-19)

### What's changed

- Updated Python minimum requirement to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307))
- Improved README with installation instructions and table of contents ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1))
- Updated package description to "Everything you need to send email in Plain" ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1))

### Upgrade instructions

- Update your Python version to 3.13 or higher

## [0.10.2](https://github.com/dropseed/plain/releases/plain-email@0.10.2) (2025-06-23)

### What's changed

- No user-facing changes. Internal documentation and tooling updates only ([82710c3](https://github.com/dropseed/plain/commit/82710c3), [9a1963d](https://github.com/dropseed/plain/commit/9a1963d), [e1f5dd3](https://github.com/dropseed/plain/commit/e1f5dd3)).

### Upgrade instructions

- No changes required
