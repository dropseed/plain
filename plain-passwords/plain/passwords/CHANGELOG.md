# plain-passwords changelog

## [0.11.0](https://github.com/dropseed/plain/releases/plain-passwords@0.11.0) (2025-09-12)

### What's changed

- Database queries now use `.query` instead of `.objects` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version updated to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Updated package description and README formatting ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- Update any custom code that references `User.objects` to use `User.query` instead

## [0.10.0](https://github.com/dropseed/plain/releases/plain-passwords@0.10.0) (2025-07-22)

### What's changed

- Updated password reset token generation and validation to use `user.id` instead of `user.pk` ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required

## [0.9.2](https://github.com/dropseed/plain/releases/plain-passwords@0.9.2) (2025-06-24)

### What's changed

- Added an initial `CHANGELOG.md` to the package so future updates are easier to track ([82710c3](https://github.com/dropseed/plain/commit/82710c3c83))

### Upgrade instructions

- No changes required
