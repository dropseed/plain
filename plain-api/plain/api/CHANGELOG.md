# plain-api changelog

## [0.30.0](https://github.com/dropseed/plain/releases/plain-api@0.30.0) (2026-04-22)

### What's changed

- **`APIView` now owns the dict/list/int/tuple/None shorthand.** Plain 0.134.0 narrowed base `View` handler returns to `Response`; `APIView` overrides `convert_value_to_response` to keep the ergonomic shorthand: return a dict or list for a `JsonResponse`, an int for a `Response(status_code=...)`, a `(status_code, data)` tuple, or `None` to raise `NotFoundError404`. The new `APIResult` type alias is exported for annotating handlers. ([1935f3f](https://github.com/dropseed/plain/commit/1935f3f))
- **`VersionedAPIView` now extends `APIView`** (it was a plain `View`), so versioned endpoints get the shorthand coercion and JSON error handling without extra wiring.

### Upgrade instructions

- Requires `plain>=0.134.0`.
- **If you returned raw data from a plain `View` subclass for a JSON endpoint** — move it to `APIView`, or wrap the value in `JsonResponse(...)` yourself. Base `View` no longer coerces.
- Annotate handlers with `APIResult` if you want a type that captures all the accepted shorthand forms: `def get(self) -> APIResult: ...`.

## [0.29.4](https://github.com/dropseed/plain/releases/plain-api@0.29.4) (2026-04-21)

### What's changed

- **Migrated `APIView` to `View.handle_exception`.** Exception-to-JSON mapping moved out of a `get_response()` wrapper and into a clean `handle_exception(exc)` override. Any `HTTPException` subclass (including user-defined ones) now maps to a JSON error response keyed off its `status_code` — previously only a fixed list (`ForbiddenError403`, `NotFoundError404`, …) was recognized. ([c1234c14be1d](https://github.com/dropseed/plain/commit/c1234c14be1d), [48effac976a9](https://github.com/dropseed/plain/commit/48effac976a9))
- **Migrated `APIKeyView` and `VersionedAPIView` to `before_request` / `after_response` hooks.** API-key validation and request-body version transforms run in `before_request`; `Cache-Control: private` and response transforms run in `after_response`. ([c1234c14be1d](https://github.com/dropseed/plain/commit/c1234c14be1d), [0da5639d17e2](https://github.com/dropseed/plain/commit/0da5639d17e2))
- **OpenAPI generation now reads `View.implemented_methods`.** Replaces the runtime `HTTPMethod`-by-`hasattr` scan — the new class-level frozenset is what the framework uses for dispatch. ([23baeea0653a](https://github.com/dropseed/plain/commit/23baeea0653a))

### Upgrade instructions

- Requires `plain>=0.133.0`.
- **If you subclassed `APIView` and overrode `get_response()`** to add custom exception handling, migrate that logic to `handle_exception(exc)` instead. Return a response to short-circuit, or call `super().handle_exception(exc)` to fall back to the default JSON error mapping.

## [0.29.3](https://github.com/dropseed/plain/releases/plain-api@0.29.3) (2026-04-17)

### What's changed

- Updated `APIKey` to use the new plain-postgres 0.96.0 field API: `UUIDField(generate=True)`, `DateTimeField(create_now=True)` / `(create_now=True, update_now=True)`, and `RandomStringField(length=40)` for `token`. Dropped the internal `generate_token()` helper — tokens are now generated per-row by Postgres via `gen_random_uuid()::text`. ([0918702](https://github.com/dropseed/plain/commit/0918702), [091bac7](https://github.com/dropseed/plain/commit/091bac7), [a44e5ec](https://github.com/dropseed/plain/commit/a44e5ec), [5d145e4](https://github.com/dropseed/plain/commit/5d145e4))

### Upgrade instructions

- Requires `plain-postgres>=0.96.0`. Run `plain postgres sync` after upgrading to reconcile column defaults.

## [0.29.2](https://github.com/dropseed/plain/releases/plain-api@0.29.2) (2026-04-13)

### What's changed

- Migrated type suppression comments to `ty: ignore` for the new ty checker version. ([4ec631a7ef51](https://github.com/dropseed/plain/commit/4ec631a7ef51))

### Upgrade instructions

- No changes required.

## [0.29.1](https://github.com/dropseed/plain/releases/plain-api@0.29.1) (2026-03-29)

### What's changed

- Removed `AddConstraint` operations from migrations — constraints are now managed by convergence. ([1f15538b008f](https://github.com/dropseed/plain/commit/1f15538b008f))

### Upgrade instructions

- No changes required.

## [0.29.0](https://github.com/dropseed/plain/releases/plain-api@0.29.0) (2026-03-28)

### What's changed

- Replaced `CharField` with `TextField` in models and migration files to match plain-postgres 0.90.0 ([5062ee4dd1fd](https://github.com/dropseed/plain/commit/5062ee4dd1fd))

### Upgrade instructions

- Requires `plain-postgres>=0.90.0`
- Replace `CharField` with `TextField` in migration files that reference this package's models

## [0.28.2](https://github.com/dropseed/plain/releases/plain-api@0.28.2) (2026-03-27)

### What's changed

- Updated OpenAPI schema generation to use `fields.TextField` instead of `fields.CharField` ([4e29f5d6cade](https://github.com/dropseed/plain/commit/4e29f5d6cade))

### Upgrade instructions

- Requires `plain>=0.129.0`. No other changes required.

## [0.28.1](https://github.com/dropseed/plain/releases/plain-api@0.28.1) (2026-03-20)

### What's changed

- Switched internal logging to use the structured framework logger (`plain.logs.get_framework_logger`) instead of the standard `logging` module ([75a8b60c91](https://github.com/dropseed/plain/commit/75a8b60c91))

### Upgrade instructions

- No changes required.

## [0.28.0](https://github.com/dropseed/plain/releases/plain-api@0.28.0) (2026-03-12)

### What's changed

- Updated all imports from `plain.models` to `plain.postgres` in models, views, migrations, and README examples.

### Upgrade instructions

- Update imports: `from plain.models` to `from plain.postgres`, `from plain import models` to `from plain import postgres`.

## [0.27.2](https://github.com/dropseed/plain/releases/plain-api@0.27.2) (2026-03-10)

### What's changed

- Updated README code examples to use typed fields (`types.ForeignKeyField` with type annotations) ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))

### Upgrade instructions

- No changes required.

## [0.27.1](https://github.com/dropseed/plain/releases/plain-api@0.27.1) (2026-03-10)

### What's changed

- Refactored OpenAPI `request_form` decorator to build the JSON schema using named intermediate dicts instead of deeply nested access, eliminating `type: ignore` comments ([f56c6454b164](https://github.com/dropseed/plain/commit/f56c6454b164))
- Added explicit type annotations to `response_schema`, `field_mappings`, and `api_versions` ([f56c6454b164](https://github.com/dropseed/plain/commit/f56c6454b164))

### Upgrade instructions

- No changes required.

## [0.27.0](https://github.com/dropseed/plain/releases/plain-api@0.27.0) (2026-03-06)

### What's changed

- Updated OpenAPI schema generator to access `view_class` directly on `URLPattern` instead of through `URLPattern.view.view_class`, adapting to the view API changes in plain 0.118.0 ([0d0c8a64cb45](https://github.com/dropseed/plain/commit/0d0c8a64cb45))

### Upgrade instructions

- Requires `plain>=0.118.0`.

## [0.26.3](https://github.com/dropseed/plain/releases/plain-api@0.26.3) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.26.2](https://github.com/dropseed/plain/releases/plain-api@0.26.2) (2026-02-04)

### What's changed

- Added `__all__` exports to `models`, `schemas`, `versioning`, and `views` modules for explicit public API boundaries ([f26a63a5c941](https://github.com/dropseed/plain/commit/f26a63a5c941))

### Upgrade instructions

- No changes required.

## [0.26.1](https://github.com/dropseed/plain/releases/plain-api@0.26.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.26.0](https://github.com/dropseed/plain/releases/plain-api@0.26.0) (2026-01-15)

### What's changed

- Added description text to the API keys admin viewset ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))

### Upgrade instructions

- No changes required

## [0.25.0](https://github.com/dropseed/plain/releases/plain-api@0.25.0) (2026-01-13)

### What's changed

- Improved README documentation with FAQs section covering common questions about optional API keys, status codes, and request body access ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-api@0.24.0) (2026-01-13)

### What's changed

- HTTP exceptions (`NotFoundError404`, `ForbiddenError403`) are now imported from `plain.http` instead of `plain.exceptions` ([b61f909](https://github.com/dropseed/plain/commit/b61f909e29))

### Upgrade instructions

- Update imports of `NotFoundError404` and `ForbiddenError403` from `plain.exceptions` to `plain.http` (e.g., `from plain.http import NotFoundError404`)

## [0.23.0](https://github.com/dropseed/plain/releases/plain-api@0.23.0) (2026-01-13)

### What's changed

- HTTP exceptions have been renamed to include the status code in the name (e.g., `Http404` → `NotFoundError404`, `PermissionDenied` → `ForbiddenError403`) ([5a1f020](https://github.com/dropseed/plain/commit/5a1f020f52))
- Response classes have been renamed to use a `Response` suffix (e.g., `ResponseRedirect` → `RedirectResponse`, `ResponseBadRequest` removed) ([fad5bf2](https://github.com/dropseed/plain/commit/fad5bf28b0))

### Upgrade instructions

- Replace `Http404` with `NotFoundError404` from `plain.exceptions`
- Replace `PermissionDenied` with `ForbiddenError403` from `plain.exceptions`
- Replace `ResponseBadRequest(...)` with `Response(..., status_code=400)` from `plain.http`

## [0.22.0](https://github.com/dropseed/plain/releases/plain-api@0.22.0) (2025-12-26)

### What's changed

- Added built-in admin views for managing API keys when `plain-admin` is installed ([960ce39](https://github.com/dropseed/plain/commit/960ce394b9))

### Upgrade instructions

- No changes required

## [0.21.1](https://github.com/dropseed/plain/releases/plain-api@0.21.1) (2025-12-22)

### What's changed

- Internal type annotation improvements in OpenAPI decorators ([539a706](https://github.com/dropseed/plain/commit/539a706760))

### Upgrade instructions

- No changes required

## [0.21.0](https://github.com/dropseed/plain/releases/plain-api@0.21.0) (2025-11-21)

### What's changed

- Updated documentation to use `ForeignKeyField` instead of `ForeignKey` to match the `plain-models` rename ([8010204](https://github.com/dropseed/plain/commit/8010204b36))

### Upgrade instructions

- If you followed the README examples using `models.ForeignKey`, update your code to use `models.ForeignKeyField` instead

## [0.20.1](https://github.com/dropseed/plain/releases/plain-api@0.20.1) (2025-11-17)

### What's changed

- Removed `ClassVar` from `query` type annotation for improved type checker compatibility ([1c624ff](https://github.com/dropseed/plain/commit/1c624ff29e))

### Upgrade instructions

- No changes required

## [0.20.0](https://github.com/dropseed/plain/releases/plain-api@0.20.0) (2025-11-14)

### What's changed

- The `related_name` parameter has been removed from `ForeignKey` fields. Reverse relationships are now accessed using explicit reverse descriptor fields ([a4b6309](https://github.com/dropseed/plain/commit/a4b630969d))

### Upgrade instructions

- Update code that accesses reverse relationships to use the new pattern. For example, if you had `api_key.users.first()`, change it to `User.query.filter(api_key=api_key).first()`

## [0.19.0](https://github.com/dropseed/plain/releases/plain-api@0.19.0) (2025-11-13)

### What's changed

- Added `query` type annotation using `ClassVar` for improved type checking support ([c3b00a6](https://github.com/dropseed/plain/commit/c3b00a6))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-api@0.18.0) (2025-11-13)

### What's changed

- Added type stubs and improved type annotations for model fields using `plain.models.types` import pattern ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-api@0.17.0) (2025-11-12)

### What's changed

- Fixed type checker warnings in OpenAPI decorator implementation ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcef))

### Upgrade instructions

- No changes required

## [0.16.3](https://github.com/dropseed/plain/releases/plain-api@0.16.3) (2025-11-03)

### What's changed

- CLI command docstrings updated to match coding style guidelines ([fdb9e80](https://github.com/dropseed/plain/commit/fdb9e80103))
- Internal model configuration updated to use `_meta` descriptor pattern ([c75441e](https://github.com/dropseed/plain/commit/c75441eba7))

### Upgrade instructions

- No changes required

## [0.16.2](https://github.com/dropseed/plain/releases/plain-api@0.16.2) (2025-10-31)

### What's changed

- Added explicit BSD-3-Clause license metadata to package configuration ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.16.1](https://github.com/dropseed/plain/releases/plain-api@0.16.1) (2025-10-20)

### What's changed

- Internal packaging configuration updated ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-api@0.16.0) (2025-10-07)

### What's changed

- Model configuration changed from `class Meta` to `model_options = models.Options()` descriptor ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))

### Upgrade instructions

- No changes required

## [0.15.2](https://github.com/dropseed/plain/releases/plain-api@0.15.2) (2025-10-06)

### What's changed

- Added type annotations throughout the package for improved IDE and type checker support ([41f6429](https://github.com/dropseed/plain/commit/41f6429892))

### Upgrade instructions

- No changes required

## [0.15.1](https://github.com/dropseed/plain/releases/plain-api@0.15.1) (2025-10-02)

### What's changed

- Updates docs references to `request.user`

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-api@0.15.0) (2025-09-25)

### What's changed

- Removed deprecated field types: `NullBooleanField` from OpenAPI schema generation ([345295d](https://github.com/dropseed/plain/commit/345295dc8a))

### Upgrade instructions

- If you were using `NullBooleanField` in your API forms, replace it with `BooleanField` with `required=False` and/or `allow_null=True` as appropriate

## [0.14.0](https://github.com/dropseed/plain/releases/plain-api@0.14.0) (2025-09-12)

### What's changed

- Model and related manager objects renamed from `objects` to `query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4711c4477a211d63c57ad8414096301))
- Minimum Python version updated to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb0d5e8f5001efccede4d58d0e26bfea))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-api@0.13.0) (2025-08-19)

### What's changed

- API views no longer use `CsrfExemptViewMixin` ([2a50a91](https://github.com/dropseed/plain/commit/2a50a9154e7fb72ea0dad860954af1f96117143e))
- Improved README documentation with better examples and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-api@0.12.0) (2025-07-22)

### What's changed

- The `APIKey` model now uses `PrimaryKeyField()` instead of `BigAutoField` for the primary key ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef126a15e48b5f85e0652adf841eb7b5c))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-api@0.11.0) (2025-07-18)

### What's changed

- Migrations have been restarted with all fields consolidated into the initial migration ([484f1b6e93](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainapi` to remove old migration records and apply the consolidated migration

## [0.10.1](https://github.com/dropseed/plain/releases/plain-api@0.10.1) (2025-06-24)

### What's changed

- Added an initial CHANGELOG for plain-api (documentation only, no functional changes) ([82710c3](https://github.com/dropseed/plain/commit/82710c3))

### Upgrade instructions

- No changes required
