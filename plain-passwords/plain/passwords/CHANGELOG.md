# plain-passwords changelog

## [0.23.4](https://github.com/dropseed/plain/releases/plain-passwords@0.23.4) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.23.3](https://github.com/dropseed/plain/releases/plain-passwords@0.23.3) (2026-02-12)

### What's changed

- Updated README examples to use `UniqueConstraint` instead of `unique=True` on email fields ([9db8e0aa5d43](https://github.com/dropseed/plain/commit/9db8e0aa5d43))
- Updated login form template example to use headless form rendering instead of `csrf_input` and `as_elements()` ([9db8e0aa5d43](https://github.com/dropseed/plain/commit/9db8e0aa5d43))

### Upgrade instructions

- No changes required.

## [0.23.2](https://github.com/dropseed/plain/releases/plain-passwords@0.23.2) (2026-02-04)

### What's changed

- Removed `@internalcode` decorator from utility functions (`urlsafe_base64_encode`, `urlsafe_base64_decode`, `unicode_ci_compare`) ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))

### Upgrade instructions

- No changes required.

## [0.23.1](https://github.com/dropseed/plain/releases/plain-passwords@0.23.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.23.0](https://github.com/dropseed/plain/releases/plain-passwords@0.23.0) (2026-01-22)

### What's changed

- Removed `db_column`, `db_collation`, and `db_comment` parameters from `PasswordField` type stubs to match upstream plain-models changes ([eed1bb6](https://github.com/dropseed/plain/commit/eed1bb6811), [49b362d](https://github.com/dropseed/plain/commit/49b362d3d3))

### Upgrade instructions

- No changes required.

## [0.22.0](https://github.com/dropseed/plain/releases/plain-passwords@0.22.0) (2026-01-13)

### What's changed

- Expanded README documentation with comprehensive coverage of password hashing, validation, views, and forms ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.21.0](https://github.com/dropseed/plain/releases/plain-passwords@0.21.0) (2026-01-13)

### What's changed

- Updated `BadRequestError400` import to use new location in `plain.http` instead of `plain.exceptions` ([b61f909](https://github.com/dropseed/plain/commit/b61f909e29))

### Upgrade instructions

- No changes required

## [0.20.0](https://github.com/dropseed/plain/releases/plain-passwords@0.20.0) (2026-01-13)

### What's changed

- Updated to use renamed `RedirectResponse` class (previously `ResponseRedirect`) ([fad5bf2](https://github.com/dropseed/plain/commit/fad5bf28b0))
- Updated to use renamed `BadRequestError400` exception (previously `BadRequest`) ([5a1f020](https://github.com/dropseed/plain/commit/5a1f020f52))

### Upgrade instructions

- No changes required

## [0.19.1](https://github.com/dropseed/plain/releases/plain-passwords@0.19.1) (2025-12-22)

### What's changed

- Updated type annotations for improved type checker compatibility ([539a706](https://github.com/dropseed/plain/commit/539a706760))

### Upgrade instructions

- No changes required

## [0.19.0](https://github.com/dropseed/plain/releases/plain-passwords@0.19.0) (2025-12-04)

### What's changed

- Improved type annotations for `CommonPasswordValidator` and password views ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-passwords@0.18.0) (2025-11-24)

### What's changed

- Password views now inherit from `AuthView` instead of using `AuthViewMixin` for better type checking support ([569afd6](https://github.com/dropseed/plain/commit/569afd606d))

### Upgrade instructions

- No changes required

## [0.17.1](https://github.com/dropseed/plain/releases/plain-passwords@0.17.1) (2025-11-20)

### What's changed

- Improved type annotations for better compatibility with type checkers ([a43145e](https://github.com/dropseed/plain/commit/a43145e697))

### Upgrade instructions

- No changes required

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
