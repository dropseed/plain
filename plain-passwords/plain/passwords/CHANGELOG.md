# plain-passwords changelog

## [0.13.0](https://github.com/dropseed/plain/releases/plain-passwords@0.13.0) (2025-10-02)

### What's changed

- Password views now inherit from `AuthViewMixin` and use `self.user` and `self.session` properties instead of accessing them through `self.request` ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- If you have custom views that inherit from `PasswordResetView`, `PasswordChangeView`, or `PasswordLoginView`, update any references to `self.request.user` to use `self.user` and `self.request.session` to use `self.session`

## [0.12.0](https://github.com/dropseed/plain/releases/plain-passwords@0.12.0) (2025-09-19)

### What's changed

- Replaced custom `constant_time_compare` utility with Python's built-in `hmac.compare_digest` for better security and performance ([55f3f55](https://github.com/dropseed/plain/commit/55f3f5596d))

### Upgrade instructions

- No changes required

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
