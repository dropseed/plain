# plain-api changelog

## [0.33.4](https://github.com/dropseed/plain/releases/plain-api@0.33.4) (2026-05-13)

### What's changed

- Adapted the OpenAPI schema generator to plain 0.144.0's new URL converter API: reads `converter.keyword` and `url_pattern.raw_route` / `url_pattern.route.converters` instead of the removed `_get_converters()` registry and `isinstance(converter, IntConverter)` checks. ([5025de26be](https://github.com/dropseed/plain/commit/5025de26be))
- The conformance fixture registers a one-off `<anything:_>` converter (regex `[\s\S]+`) so schemathesis's newline-bearing path inputs still reach the JSON 404 handler — the default `<path:>` converter's `.+` doesn't match `\n`. ([28dba1d2ed](https://github.com/dropseed/plain/commit/28dba1d2ed))
- Centralized 5xx logging and exception attachment now happen in the framework's `View._respond_to_exception`, so `APIView` no longer needs to override `handle_exception` to keep responses observable. ([2634fd1d1c](https://github.com/dropseed/plain/commit/2634fd1d1c))

### Upgrade instructions

- No code changes required. Requires `plain>=0.144.0`.

## [0.33.3](https://github.com/dropseed/plain/releases/plain-api@0.33.3) (2026-05-12)

### What's changed

- README updated for the renamed asset compile namespace: `[tool.plain.assets.run]` (was `[tool.plain.assets.build.run]`). See [plain-assets 0.3.0](../../../plain-assets/plain/assets/CHANGELOG.md). ([3b30b62309](https://github.com/dropseed/plain/commit/3b30b62309))

### Upgrade instructions

- No code changes required. If you copied the OpenAPI build snippet into your `pyproject.toml`, rename its section header to `[tool.plain.assets.run]`.

## [0.33.2](https://github.com/dropseed/plain/releases/plain-api@0.33.2) (2026-05-12)

### What's changed

- README updated to reference the new `[tool.plain.assets.build.run]` namespace (was `[tool.plain.build.run]`) for the OpenAPI build step. See [plain-assets 0.2.0](../../../plain-assets/plain/assets/CHANGELOG.md). ([f698ec3436](https://github.com/dropseed/plain/commit/f698ec3436))

### Upgrade instructions

- No code changes required. If you copy-pasted the OpenAPI build snippet into your `pyproject.toml`, update its section header from `[tool.plain.build.run]` to `[tool.plain.assets.build.run]`.

## [0.33.1](https://github.com/dropseed/plain/releases/plain-api@0.33.1) (2026-05-08)

### What's changed

- Suppress `ty unresolved-import` warnings on the optional `openapi-spec-validator` and `referencing` imports inside `validate_openapi_schema`. They're guarded by an import-time `try/except`, but ty doesn't see the install-extras gate. ([7d831926bb](https://github.com/dropseed/plain/commit/7d831926bb))

### Upgrade instructions

- No changes required.

## [0.33.0](https://github.com/dropseed/plain/releases/plain-api@0.33.0) (2026-05-07)

### What's changed

- **Auto-200 from return type annotations.** `def get(self) -> MyTypedDict:` now emits a 200 response schema automatically — no decorator required. The annotation can also be a union (e.g. `MyDict | Response`); the first TypedDict member wins. Decorator-declared 2xx responses still take precedence. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **Method/class docstrings drive operation `summary` and `description`.** PEP 257 split: first paragraph (joined into a single line) becomes `summary`; the rest becomes `description`. A leading `GET /path/` line is dropped because the URL already lives in `paths`. The view class docstring is the fallback when a method has none. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **Nested TypedDicts now register as named components.** Previously `@openapi.response_typed_dict(200, Outer)` inlined `Inner` inside `Outer.properties`; now `Inner` is its own `#/components/schemas/Inner` and `Outer` references it by `$ref`. Cycle-safe via a placeholder. The same happens for the new auto-200 path. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **`openapi_parameters` class attribute** is walked via the MRO and merged with auto-extracted URL path params (`(name, in)`-keyed; `$ref` parameters keyed by ref string). Subclasses can extend or override their parents' parameters. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **Path params now merge with declared parameters** instead of being suppressed. Previously declaring any `parameters` in `@openapi.schema` blocked auto-extraction of URL path params, forcing you to re-list them; now they're merged by `(name, in)` with declared entries winning. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **`OpenAPISchemaGenerator.include_view(view_class)` filter hook** for restricting the schema to a subset of views (e.g. only public ones). Default returns True. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **`schema_from_type` improvements**: `Literal[...]` → `enum` (string/integer/boolean specialized; mixed types fall back to a bare `enum`); `dict[str, V]` → `additionalProperties` (was previously a bug that crashed on non-TypedDict value types); TypedDict annotations resolve via `get_type_hints` so `from __future__ import annotations` and forward refs work. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))
- **`APIResult` accepts `Mapping[str, Any]`** (instead of `dict[str, Any]`) so TypedDict return annotations on view methods satisfy Liskov against the base view. TypedDicts aren't `dict` per PEP 589. ([e9fdfcfe9c60](https://github.com/dropseed/plain/commit/e9fdfcfe9c60))

### Upgrade instructions

- **If you consume the generated OpenAPI spec for client codegen and snapshot it** — refresh the snapshot. Nested TypedDicts that previously appeared inlined under their parent will now appear as their own `#/components/schemas/<Name>` entries with the parent referencing them via `$ref`. This is what most codegen tools want, but it does change the spec shape.
- All other changes are additive; no migration required.

## [0.32.0](https://github.com/dropseed/plain/releases/plain-api@0.32.0) (2026-05-07)

### What's changed

- **Dropped the `int` return shorthand from `APIView`.** `return 200` was ambiguous (what should the body be?) and broke content-type conformance for 4xx/5xx responses. Return a `Response`, dict, list, tuple, or `None` instead. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2))
- **Redesigned `ErrorSchema`.** Dropped the always-empty `url` field and added an optional `errors: list[{field, message}]` so structured field errors flow to clients without flattening. `handle_exception` populates it from `error_dict`-shaped `ValidationError`s. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2))
- **`APIView` now renders 415 responses for Content-Type mismatches.** Pairs with the new `UnsupportedMediaTypeError415` exception in plain 0.141.0 — bad Content-Type on a JSON/form endpoint now returns a clean 415 with `error_id: "unsupported_media_type"` instead of a 500. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2))
- **OpenAPI generator improvements.** Path converters emit native types (`<int:>` → `type: integer`, `<uuid:>` → `string + format: uuid`); `<name>` shorthand is translated to `{name}` parameters; default `operationId` is `{ViewClass}_{method}`; views that declare `openapi_security_schemes` (e.g. `APIKeyView` → `BearerAuth`) automatically emit `securitySchemes` and per-operation `security`. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2), [2fa13eda77de](https://github.com/dropseed/plain/commit/2fa13eda77de))
- **New `openapi.json_content`, `openapi.json_body`, and `openapi.link_to` helpers** to cut the `application/json` envelope and link-to-by-operationId boilerplate in spec-decorated views. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2))
- **New `JsonNotFoundView` catch-all** so unmatched paths under an API prefix return a JSON 404 instead of the framework's HTML error page. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2))
- **`APIKey.is_expired()` helper** + fixed a naive-datetime comparison in expiry checks. ([2f2d4d5e6138](https://github.com/dropseed/plain/commit/2f2d4d5e6138))
- **Generated OpenAPI specs are validated locally** via `openapi-spec-validator` in tests. ([a57b1e6bb93f](https://github.com/dropseed/plain/commit/a57b1e6bb93f))
- Tightened `APIKeyView` typing to `View[APIResult]` so it composes cleanly with `APIView` under ty. ([b5f38ef976d2](https://github.com/dropseed/plain/commit/b5f38ef976d2))
- README updates covering the new OpenAPI affordances. ([034aa5a820e1](https://github.com/dropseed/plain/commit/034aa5a820e1))

### Upgrade instructions

- Requires `plain>=0.141.0`.
- **If any of your `APIView` handlers `return <int>`** (e.g. `return 204`) — change them to return a `Response(status_code=...)` or a `(body, status_code)` tuple.
- **If you consume `ErrorSchema` from clients** — the `url` field is gone and the new optional `errors` list may now be present for validation errors.
- **If you were rendering 415s manually** when a request hit an `APIView` with the wrong Content-Type — you can drop that, plain-api now handles it automatically.

## [0.31.1](https://github.com/dropseed/plain/releases/plain-api@0.31.1) (2026-05-05)

### What's changed

- Tightened internal type annotations for ty 0.0.33. ([4b9d1db1](https://github.com/dropseed/plain/commit/4b9d1db1))
- Exposes `__version__` from `importlib.metadata` on `plain.api`. ([c6cf6edb](https://github.com/dropseed/plain/commit/c6cf6edb))

### Upgrade instructions

- No changes required.

## [0.31.0](https://github.com/dropseed/plain/releases/plain-api@0.31.0) (2026-04-24)

### What's changed

- **`APIView` now subclasses `View[APIResult]`.** plain 0.136.0 made `View` generic over its handler return type, so `APIView` parameterizes it with `APIResult` — type checkers now see `get` / `post` / etc. as returning `APIResult` (dict, list, int, tuple, None, or `Response`) instead of just `Response`. ([9c0c12df13fd](https://github.com/dropseed/plain/commit/9c0c12df13fd))
- **Renamed `APIView.convert_value_to_response` → `APIView.convert_result_to_response`** to match the rename in plain 0.136.0. ([11c8fe16b544](https://github.com/dropseed/plain/commit/11c8fe16b544))

### Upgrade instructions

- Requires `plain>=0.136.0`.
- **If you overrode `convert_value_to_response` on an `APIView` subclass** — rename it to `convert_result_to_response` and update the parameter name from `value` to `result`.

## [0.30.1](https://github.com/dropseed/plain/releases/plain-api@0.30.1) (2026-04-23)

### What's changed

- `APIView` and `VersionedAPIView` type hints switched from `ResponseBase` to `Response` after plain 0.135.0 merged the two. The `APIResult` type alias, `after_response`, `handle_exception`, and `convert_value_to_response` now reference `Response`. ([f5007281d7fa](https://github.com/dropseed/plain/commit/f5007281d7fa))
- Dropped the `requests` dependency from the OpenAPI validator command — `plain api generate-openapi --validate` now calls the Swagger validator via `urllib.request` from the standard library. ([1a9050fc42e0](https://github.com/dropseed/plain/commit/1a9050fc42e0))

### Upgrade instructions

- Requires `plain>=0.135.0`.

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
