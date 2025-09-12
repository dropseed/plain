# plain-loginlink changelog

## [0.12.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.12.0) (2025-09-12)

### What's changed

- Model managers renamed from `objects` to `query` for consistency with Plain framework ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version raised from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- README updated with proper formatting and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- Replace any custom usage of `User.objects` with `User.query` in your loginlink-related code

## [0.11.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.11.0) (2025-07-22)

### What's changed

- Login link generation now uses `user.id` instead of `user.pk` for consistency ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required.

## [0.10.1](https://github.com/dropseed/plain/releases/plain-loginlink@0.10.1) (2025-06-23)

### What's changed

- No user-facing changes in this release.

### Upgrade instructions

- No changes required.
