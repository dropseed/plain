# plain changelog

## [0.60.0](https://github.com/dropseed/plain/releases/plain@0.60.0) (2025-08-27)

### What's changed

- Added new `APP_VERSION` setting that defaults to the project version from `pyproject.toml` ([57fb948d46](https://github.com/dropseed/plain/commit/57fb948d46))
- Updated `get_app_name_from_pyproject()` to `get_app_info_from_pyproject()` to return both name and version ([57fb948d46](https://github.com/dropseed/plain/commit/57fb948d46))

### Upgrade instructions

- No changes required

## [0.59.0](https://github.com/dropseed/plain/releases/plain@0.59.0) (2025-08-22)

### What's changed

- Added new `APP_NAME` setting that defaults to the project name from `pyproject.toml` ([1a4d60e](https://github.com/dropseed/plain/commit/1a4d60e787))
- Template views now validate that `get_template_names()` returns a list instead of a string ([428a64f](https://github.com/dropseed/plain/commit/428a64f8cc))
- Object views now use cached properties for `.object` and `.objects` to improve performance ([bd0507a](https://github.com/dropseed/plain/commit/bd0507a72c))
- Improved `plain upgrade` command to suggest using subagents when there are more than 3 package updates ([497c30d](https://github.com/dropseed/plain/commit/497c30d445))

### Upgrade instructions

- In object views, `self.load_object()` is no longer necessary as `self.object` is now a cached property.

## [0.58.0](https://github.com/dropseed/plain/releases/plain@0.58.0) (2025-08-19)

### What's changed

- Complete rewrite of CSRF protection using modern Sec-Fetch-Site headers and origin validation ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- Replaced CSRF view mixin with path-based exemptions using `CSRF_EXEMPT_PATHS` setting ([2a50a9154e](https://github.com/dropseed/plain/commit/2a50a9154e))
- Renamed `HTTPS_REDIRECT_EXEMPT` to `HTTPS_REDIRECT_EXEMPT_PATHS` with leading slash requirement ([b53d3bb7a7](https://github.com/dropseed/plain/commit/b53d3bb7a7))
- Agent commands now print prompts directly when running in Claude Code or Codex Sandbox environments ([6eaed8ae3b](https://github.com/dropseed/plain/commit/6eaed8ae3b))

### Upgrade instructions

- Remove any usage of `CsrfExemptViewMixin` and `request.csrf_exempt` and add exempt paths to the `CSRF_EXEMPT_PATHS` setting instead (ex. `CSRF_EXEMPT_PATHS = [r"^/api/", r"/webhooks/.*"]` -- but consider first whether the view still needs CSRF exemption under the new implementation)
- Replace `HTTPS_REDIRECT_EXEMPT` with `HTTPS_REDIRECT_EXEMPT_PATHS` and ensure patterns include leading slash (ex. `[r"^/health$", r"/api/internal/.*"]`)
- Remove all CSRF cookie and token related settings - the new implementation doesn't use cookies or tokens (ex. `{{ csrf_input }}` and `{{ csrf_token }}`)

## [0.57.0](https://github.com/dropseed/plain/releases/plain@0.57.0) (2025-08-15)

### What's changed

- The `ResponsePermanentRedirect` class has been removed; use `ResponseRedirect` with `status_code=301` instead ([d5735ea](https://github.com/dropseed/plain/commit/d5735ea4f8))
- The `RedirectView.permanent` attribute has been replaced with `status_code` for more flexible redirect status codes ([12dda16](https://github.com/dropseed/plain/commit/12dda16731))
- Updated `RedirectView` initialization parameters: `url_name` replaces `pattern_name`, `preserve_query_params` replaces `query_string`, and removed 410 Gone functionality ([3b9ca71](https://github.com/dropseed/plain/commit/3b9ca713bf))

### Upgrade instructions

- Replace `ResponsePermanentRedirect` imports with `ResponseRedirect` and pass `status_code=301` to the constructor
- Update `RedirectView` subclasses to use `status_code=301` instead of `permanent=True`
- Replace `pattern_name` with `url_name` in RedirectView usage
- Replace `query_string=True` with `preserve_query_params=True` in RedirectView usage

## [0.56.1](https://github.com/dropseed/plain/releases/plain@0.56.1) (2025-07-30)

### What's changed

- Improved `plain install` command instructions to be more explicit about completing code modifications ([83292225db](https://github.com/dropseed/plain/commit/83292225db))

### Upgrade instructions

- No changes required

## [0.56.0](https://github.com/dropseed/plain/releases/plain@0.56.0) (2025-07-25)

### What's changed

- Added `plain install` command to install Plain packages with agent-assisted setup ([bf1873e](https://github.com/dropseed/plain/commit/bf1873eb81))
- Added `--print` option to agent commands (`plain install` and `plain upgrade`) to print prompts without running the agent ([9721331](https://github.com/dropseed/plain/commit/9721331e40))
- The `plain docs` command now automatically converts hyphens to dots in package names (e.g., `plain-models` → `plain.models`) ([1e3edc1](https://github.com/dropseed/plain/commit/1e3edc10f7))
- Moved `plain-upgrade` functionality into plain core, eliminating the need for a separate package ([473f9bb](https://github.com/dropseed/plain/commit/473f9bb718))

### Upgrade instructions

- No changes required

## [0.55.0](https://github.com/dropseed/plain/releases/plain@0.55.0) (2025-07-22)

### What's changed

- Updated URL pattern documentation examples to use `id` instead of `pk` in URL kwargs ([b656ee6](https://github.com/dropseed/plain/commit/b656ee6e4e))
- Updated views documentation examples to use `id` instead of `pk` for DetailView, UpdateView, and DeleteView ([b656ee6](https://github.com/dropseed/plain/commit/b656ee6e4e))

### Upgrade instructions

- Update your URL patterns from `<int:pk>` to `<int:id>` in your URLconf
- Update view code that accesses `self.url_kwargs["pk"]` to use `self.url_kwargs["id"]` instead
- Replace any QuerySet filters using `pk` with `id` (e.g., `Model.objects.get(pk=1)` becomes `Model.objects.get(id=1)`)

## [0.54.1](https://github.com/dropseed/plain/releases/plain@0.54.1) (2025-07-20)

### What's changed

- Fixed OpenTelemetry route naming to include leading slash for consistency with HTTP paths ([9d77268](https://github.com/dropseed/plain/commit/9d77268988))

### Upgrade instructions

- No changes required

## [0.54.0](https://github.com/dropseed/plain/releases/plain@0.54.0) (2025-07-18)

### What's changed

- Added OpenTelemetry instrumentation for HTTP requests, views, and template rendering ([b0224d0418](https://github.com/dropseed/plain/commit/b0224d0418))
- Added `plain-observer` package reference to plain README ([f29ff4dafe](https://github.com/dropseed/plain/commit/f29ff4dafe))

### Upgrade instructions

- No changes required

## [0.53.0](https://github.com/dropseed/plain/releases/plain@0.53.0) (2025-07-18)

### What's changed

- Added a `pluralize` filter for Jinja templates to handle singular/plural forms ([4cef9829ed](https://github.com/dropseed/plain/commit/4cef9829ed))
- Added `get_signed_cookie()` method to `HttpRequest` for retrieving and verifying signed cookies ([f8796c8786](https://github.com/dropseed/plain/commit/f8796c8786))
- Improved CLI error handling by using `click.UsageError` instead of manual error printing ([88f06c5184](https://github.com/dropseed/plain/commit/88f06c5184))
- Simplified preflight check success message ([adffc06152](https://github.com/dropseed/plain/commit/adffc06152))

### Upgrade instructions

- No changes required

## [0.52.2](https://github.com/dropseed/plain/releases/plain@0.52.2) (2025-06-27)

### What's changed

- Improved documentation for the assets subsystem: the `AssetsRouter` reference in the Assets README now links directly to the source code for quicker navigation ([65437e9](https://github.com/dropseed/plain/commit/65437e9bb1a522c7ababe0fc195f63bc5fd6c4d4))

### Upgrade instructions

- No changes required

## [0.52.1](https://github.com/dropseed/plain/releases/plain@0.52.1) (2025-06-27)

### What's changed

- Fixed `plain help` output on newer versions of Click by switching from `MultiCommand` to `Group` when determining sub-commands ([9482e42](https://github.com/dropseed/plain/commit/9482e421ac408ac043d341edda3dba9f27694f08))

### Upgrade instructions

- No changes required

## [0.52.0](https://github.com/dropseed/plain/releases/plain@0.52.0) (2025-06-26)

### What's changed

- Added `plain-changelog` as a standalone executable so you can view changelogs without importing the full framework ([e4e7324](https://github.com/dropseed/plain/commit/e4e7324cd284c800ff957933748d6639615cbea6))
- Removed the runtime dependency on the `packaging` library by replacing it with an internal version-comparison helper ([e4e7324](https://github.com/dropseed/plain/commit/e4e7324cd284c800ff957933748d6639615cbea6))
- Improved the error message when a package changelog cannot be found, now showing the path that was looked up ([f3c82bb](https://github.com/dropseed/plain/commit/f3c82bb59e07c1bddbdb2557f2043e039c1cd1e9))
- Fixed an f-string issue that broke `plain.debug.dd` on Python 3.11 ([ed24276](https://github.com/dropseed/plain/commit/ed24276a12191e4c8903369002dd32b69eb358b3))

### Upgrade instructions

- No changes required

## [0.51.0](https://github.com/dropseed/plain/releases/plain@0.51.0) (2025-06-24)

### What's changed

- New `plain changelog` CLI sub-command to quickly view a package’s changelog from the terminal. Supports `--from`/`--to` flags to limit the version range ([50f0de7](https://github.com/dropseed/plain/commit/50f0de721f263ec6274852bd8838f4e5037b27dc)).

### Upgrade instructions

- No changes required

## [0.50.0](https://github.com/dropseed/plain/releases/plain@0.50.0) (2025-06-23)

### What's changed

- The URL inspection command has moved; run `plain urls list` instead of the old `plain urls` command ([6146fcb](https://github.com/dropseed/plain/commit/6146fcba536c551277d625bd750c385431ea18eb))
- `plain preflight` gains a simpler `--database` flag that enables database checks for your default database. The previous behaviour that accepted one or more database aliases has been removed ([d346d81](https://github.com/dropseed/plain/commit/d346d81567d2cc45bbed93caba18a195de10c572))
- Settings overhaul: use a single `DATABASE` setting instead of `DATABASES`/`DATABASE_ROUTERS` ([d346d81](https://github.com/dropseed/plain/commit/d346d81567d2cc45bbed93caba18a195de10c572))

### Upgrade instructions

- Update any scripts or documentation that call `plain urls …`:
    - Replace `plain urls --flat` with `plain urls list --flat`
- If you invoke preflight checks in CI or locally:
    - Replace `plain preflight --database <alias>` (or multiple aliases) with the new boolean flag: `plain preflight --database`
- In `settings.py` migrate to the new database configuration:

    ```python
    # Before
    DATABASES = {
        "default": {
            "ENGINE": "plain.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

    # After
    DATABASE = {
        "ENGINE": "plain.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
    ```

    Remove any `DATABASES` and `DATABASE_ROUTERS` settings – they are no longer read.
