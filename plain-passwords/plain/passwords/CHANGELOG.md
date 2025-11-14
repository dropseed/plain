# plain-passwords changelog

## [0.17.0](https://github.com/dropseed/plain/releases/plain-passwords@0.17.0) (2025-11-13)

### What's changed

- Added typed `PasswordField` for better IDE and type checker support when using type annotations in model definitions ([dc1f9c4](https://github.com/dropseed/plain/commit/dc1f9c4808))

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-passwords@0.16.0) (2025-11-12)

### What's changed

- `BasePasswordHasher` now inherits from `ABC` and uses `@abstractmethod` decorators for better type checking and enforcement ([4f2d1d4](https://github.com/dropseed/plain/commit/4f2d1d47c0))
- Improved type annotations and fixed type checker warnings throughout the package ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa92))

### Upgrade instructions

- No changes required

## [0.15.1](https://github.com/dropseed/plain/releases/plain-passwords@0.15.1) (2025-10-31)

### What's changed

- Added BSD-3-Clause license metadata to package configuration ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-passwords@0.15.0) (2025-10-07)

### What's changed

- Updated internal model metadata access to use `_model_meta` instead of `_meta` ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-passwords@0.14.0) (2025-10-06)

### What's changed

- Removed unused password hashers (`PBKDF2SHA1PasswordHasher`, `Argon2PasswordHasher`, `BCryptSHA256PasswordHasher`, `BCryptPasswordHasher`, and `ScryptPasswordHasher`) - only `PBKDF2PasswordHasher` remains ([a9acb74](https://github.com/dropseed/plain/commit/a9acb74268))
- Added comprehensive type annotations throughout the package for better IDE support and type checking ([a9acb74](https://github.com/dropseed/plain/commit/a9acb74268))

### Upgrade instructions

- If you were using a non-default password hasher (`pbkdf2_sha1`, `argon2`, `bcrypt_sha256`, `bcrypt`, or `scrypt`), you'll need to implement your own custom hasher class or migrate existing passwords to use the default `PBKDF2PasswordHasher`
- If you have custom code that referenced the removed hasher classes, you'll need to update those imports

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
