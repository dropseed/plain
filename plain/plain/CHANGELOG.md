# plain changelog

## [0.103.0](https://github.com/dropseed/plain/releases/plain@0.103.0) (2026-01-30)

### What's changed

- `plain docs` now shows markdown documentation by default (previously required `--source`), with a new `--symbols` flag to show only the symbolicated API surface ([b71dab9d5d](https://github.com/dropseed/plain/commit/b71dab9d5d))
- `plain docs --list` now shows all official Plain packages (installed and uninstalled) with descriptions and install status ([9cba705d62](https://github.com/dropseed/plain/commit/9cba705d62))
- `plain docs` for uninstalled packages now shows the install command and an online docs URL instead of a generic error ([9cba705d62](https://github.com/dropseed/plain/commit/9cba705d62))
- Removed the `plain agent context` command and the `SessionStart` hook setup — agent rules now provide context directly without needing a startup hook ([88d9424643](https://github.com/dropseed/plain/commit/88d9424643))
- `plain agent install` now cleans up old SessionStart hooks from `.claude/settings.json` ([88d9424643](https://github.com/dropseed/plain/commit/88d9424643))

### Upgrade instructions

- The `--source` flag for `plain docs` has been removed. Use `--symbols` instead to see the symbolicated API surface.
- The `--open` flag for `plain docs` has been removed.
- Run `plain agent install` to clean up the old SessionStart hook from your `.claude/settings.json`.

## [0.102.0](https://github.com/dropseed/plain/releases/plain@0.102.0) (2026-01-28)

### What's changed

- Refactored agent integration from skills-based to rules-based: packages now provide `agents/.claude/rules/` files and `agents/.claude/skills/` directories instead of `skills/` directories ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))
- The `plain agent install` command now copies both rules (`.md` files) and skills to the project's `.claude/` directory, and cleans up orphaned `plain*` items ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))
- Removed standalone skills (`plain-docs`, `plain-shell`, `plain-request`) that are now provided as passive rules instead ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))

### Upgrade instructions

- Run `plain agent install` to update your `.claude/` directory with the new rules-based structure.

## [0.101.2](https://github.com/dropseed/plain/releases/plain@0.101.2) (2026-01-28)

### What's changed

- When `load_dotenv()` is called with `override=False` (the default), command substitution is now skipped for keys that already exist in `os.environ`. This prevents redundant command execution in child processes that re-load the `.env` file after inheriting resolved values from the parent, avoiding multiple auth prompts with tools like the 1Password CLI ([2f6ff93499](https://github.com/dropseed/plain/commit/2f6ff93499))
- The `_execute_command` helper now uses `stdout=subprocess.PIPE` instead of `capture_output=True`, allowing stderr/tty to pass through for interactive prompts ([2f6ff93499](https://github.com/dropseed/plain/commit/2f6ff93499))
- Updated templates README examples to use `id` instead of `pk` ([837d345d23](https://github.com/dropseed/plain/commit/837d345d23))
- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.101.1](https://github.com/dropseed/plain/releases/plain@0.101.1) (2026-01-17)

### What's changed

- Fixed a crash when running the development server with `--reload` when an app's `assets` directory doesn't exist ([df33f93ece](https://github.com/dropseed/plain/commit/df33f93ece))
- The `plain agent install` command now preserves user-created skills (those without the `plain-` prefix) instead of removing them as orphans ([bbc87498ed](https://github.com/dropseed/plain/commit/bbc87498ed))

### Upgrade instructions

- No changes required.

## [0.101.0](https://github.com/dropseed/plain/releases/plain@0.101.0) (2026-01-15)

### What's changed

- The `plain server` command now accepts `--workers auto` (or `WEB_CONCURRENCY=auto`) to automatically set worker count based on CPU count ([02a1769948](https://github.com/dropseed/plain/commit/02a1769948))
- Response headers can now be set to `None` to opt out of default headers; `None` values are filtered out at the WSGI layer rather than being deleted by middleware ([cbf27e728d](https://github.com/dropseed/plain/commit/cbf27e728d))
- Removed unused `Response` methods: `serialize_headers`, `serialize`, file-like interface stubs (`write`, `flush`, `tell`, `readable`, `seekable`, `writable`, `writelines`), `text` property, pickling support, and `getvalue` ([cbf27e728d](https://github.com/dropseed/plain/commit/cbf27e728d))

### Upgrade instructions

- No changes required

## [0.100.1](https://github.com/dropseed/plain/releases/plain@0.100.1) (2026-01-15)

### What's changed

- The `plain agent install` command now only sets up session hooks for Claude Code, not Codex, since the `settings.json` hook format is Claude Code-specific ([a41e08bcd2](https://github.com/dropseed/plain/commit/a41e08bcd2))

### Upgrade instructions

- No changes required

## [0.100.0](https://github.com/dropseed/plain/releases/plain@0.100.0) (2026-01-15)

### What's changed

- The `plain skills` command has been renamed to `plain agent` with new subcommands: `plain agent install` (installs skills and sets up hooks), `plain agent skills` (lists available skills), and `plain agent context` (outputs framework context) ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))
- Added `SessionStart` hook that automatically runs `plain agent context` at the start of every Claude Code or Codex session, providing framework context without needing a separate skill ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))
- The `plain-principles` skill has been removed - its content is now provided by the `plain agent context` command via the SessionStart hook ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))
- Added `--no-headers` and `--no-body` flags to `plain request` for limiting output ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))

### Upgrade instructions

- Replace `plain skills --install` with `plain agent install`
- Replace `plain skills` (without flags) with `plain agent skills`
- Run `plain agent install` to set up the new SessionStart hook in your project's `.claude/` or `.codex/` directory

## [0.99.0](https://github.com/dropseed/plain/releases/plain@0.99.0) (2026-01-15)

### What's changed

- Added `plain.utils.dotenv` module with `load_dotenv()` and `parse_dotenv()` functions for bash-compatible `.env` file parsing, supporting variable expansion, command substitution, multiline values, and escape sequences ([a9b2dc3e16](https://github.com/dropseed/plain/commit/a9b2dc3e16))

### Upgrade instructions

- No changes required

## [0.98.1](https://github.com/dropseed/plain/releases/plain@0.98.1) (2026-01-13)

### What's changed

- Fixed `INSTALLED_PACKAGES` not being optional in user settings, restoring the default empty list behavior ([820773c473](https://github.com/dropseed/plain/commit/820773c473))

### Upgrade instructions

- No changes required

## [0.98.0](https://github.com/dropseed/plain/releases/plain@0.98.0) (2026-01-13)

### What's changed

- The `plain skills --install` command now removes orphaned skills from destination directories when skills are renamed or removed from packages ([d51294ace1](https://github.com/dropseed/plain/commit/d51294ace1))
- Added README documentation for `plain.skills` with available skills and installation instructions ([7c90fc8595](https://github.com/dropseed/plain/commit/7c90fc8595))

### Upgrade instructions

- No changes required

## [0.97.0](https://github.com/dropseed/plain/releases/plain@0.97.0) (2026-01-13)

### What's changed

- HTTP exceptions (`NotFoundError404`, `ForbiddenError403`, `BadRequestError400`, and `SuspiciousOperationError400` variants) moved from `plain.exceptions` to `plain.http.exceptions` and are now exported from `plain.http` ([b61f909e29](https://github.com/dropseed/plain/commit/b61f909e29))

### Upgrade instructions

- Update imports of HTTP exceptions from `plain.exceptions` to `plain.http`:

    ```python
    # Before
    from plain.exceptions import NotFoundError404, ForbiddenError403, BadRequestError400

    # After
    from plain.http import NotFoundError404, ForbiddenError403, BadRequestError400
    ```

## [0.96.0](https://github.com/dropseed/plain/releases/plain@0.96.0) (2026-01-13)

### What's changed

- Response classes renamed for consistency: `ResponseRedirect` → `RedirectResponse`, `ResponseNotModified` → `NotModifiedResponse`, `ResponseNotAllowed` → `NotAllowedResponse` ([fad5bf28b0](https://github.com/dropseed/plain/commit/fad5bf28b0))
- Redundant response classes removed: `ResponseNotFound`, `ResponseForbidden`, `ResponseBadRequest`, `ResponseGone`, `ResponseServerError` - use `Response(status_code=X)` instead ([fad5bf28b0](https://github.com/dropseed/plain/commit/fad5bf28b0))
- HTTP exceptions renamed to include status code suffix: `Http404` → `NotFoundError404`, `PermissionDenied` → `ForbiddenError403`, `BadRequest` → `BadRequestError400`, `SuspiciousOperation` → `SuspiciousOperationError400` ([5a1f020f52](https://github.com/dropseed/plain/commit/5a1f020f52))
- Added `Secret[T]` type annotation for masking sensitive settings like `SECRET_KEY` in CLI output ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- Added `ENV_SETTINGS_PREFIXES` setting to configure which environment variable prefixes are checked for settings (defaults to `["PLAIN_"]`) ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- New `plain settings list` and `plain settings get` CLI commands for viewing settings with their sources ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- Added preflight check for unused environment variables matching configured prefixes ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- Renamed `request.meta` to `request.environ` for clarity ([786b95bef8](https://github.com/dropseed/plain/commit/786b95bef8))
- Added `request.query_string` and `request.content_length` properties ([786b95bef8](https://github.com/dropseed/plain/commit/786b95bef8), [76dfd477d2](https://github.com/dropseed/plain/commit/76dfd477d2))
- Renamed X-Forwarded settings: `USE_X_FORWARDED_HOST` → `HTTP_X_FORWARDED_HOST`, `USE_X_FORWARDED_PORT` → `HTTP_X_FORWARDED_PORT`, `USE_X_FORWARDED_FOR` → `HTTP_X_FORWARDED_FOR` ([22f241a55c](https://github.com/dropseed/plain/commit/22f241a55c))
- Changed `HTTPS_PROXY_HEADER` from a tuple to a string format (e.g., `"X-Forwarded-Proto: https"`) ([7ac2a431b6](https://github.com/dropseed/plain/commit/7ac2a431b6))

### Upgrade instructions

- Replace Response class imports and usages:
    - `ResponseRedirect` → `RedirectResponse`
    - `ResponseNotModified` → `NotModifiedResponse`
    - `ResponseNotAllowed` → `NotAllowedResponse`
    - `ResponseNotFound` → `Response(status_code=404)`
    - `ResponseForbidden` → `Response(status_code=403)`
    - `ResponseBadRequest` → `Response(status_code=400)`
    - `ResponseGone` → `Response(status_code=410)`
    - `ResponseServerError` → `Response(status_code=500)`
- Replace exception imports and usages:
    - `Http404` → `NotFoundError404`
    - `PermissionDenied` → `ForbiddenError403`
    - `BadRequest` → `BadRequestError400`
    - `SuspiciousOperation` → `SuspiciousOperationError400`
    - `SuspiciousMultipartForm` → `SuspiciousMultipartFormError400`
    - `SuspiciousFileOperation` → `SuspiciousFileOperationError400`
    - `TooManyFieldsSent` → `TooManyFieldsSentError400`
    - `TooManyFilesSent` → `TooManyFilesSentError400`
    - `RequestDataTooBig` → `RequestDataTooBigError400`
- Replace `request.meta` with `request.environ`
- Rename X-Forwarded settings in your configuration:
    - `USE_X_FORWARDED_HOST` → `HTTP_X_FORWARDED_HOST`
    - `USE_X_FORWARDED_PORT` → `HTTP_X_FORWARDED_PORT`
    - `USE_X_FORWARDED_FOR` → `HTTP_X_FORWARDED_FOR`
- Update `HTTPS_PROXY_HEADER` from tuple format to string format:

    ```python
    # Before
    HTTPS_PROXY_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # After
    HTTPS_PROXY_HEADER = "X-Forwarded-Proto: https"
    ```

- Replace `plain setting <name>` command with `plain settings get <name>`

## [0.95.0](https://github.com/dropseed/plain/releases/plain@0.95.0) (2025-12-22)

### What's changed

- Improved thread worker server shutdown behavior with `cancel_futures=True` for faster and cleaner process termination ([72d0620](https://github.com/dropseed/plain/commit/72d0620094))

### Upgrade instructions

- No changes required

## [0.94.0](https://github.com/dropseed/plain/releases/plain@0.94.0) (2025-12-12)

### What's changed

- `FormFieldMissingError` exceptions are now automatically converted to HTTP 400 Bad Request responses with a warning log instead of causing a 500 error ([b38f6e5](https://github.com/dropseed/plain/commit/b38f6e50db))

### Upgrade instructions

- No changes required

## [0.93.1](https://github.com/dropseed/plain/releases/plain@0.93.1) (2025-12-09)

### What's changed

- Added type annotation for `request.unique_id` attribute to improve IDE support and type checking ([23af501](https://github.com/dropseed/plain/commit/23af501d09))

### Upgrade instructions

- No changes required

## [0.93.0](https://github.com/dropseed/plain/releases/plain@0.93.0) (2025-12-04)

### What's changed

- Improved type annotations across forms, HTTP handling, logging, and other core modules for better IDE support and type checking ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))
- Internal refactor of `TimestampSigner` to use composition instead of inheritance from `Signer`, maintaining the same public API ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.92.0](https://github.com/dropseed/plain/releases/plain@0.92.0) (2025-12-01)

### What's changed

- Added `request.client_ip` property to get the client's IP address, with support for `X-Forwarded-For` header when behind a trusted proxy ([cb0bc5d](https://github.com/dropseed/plain/commit/cb0bc5d08f))
- Added `USE_X_FORWARDED_FOR` setting to enable reading client IP from `X-Forwarded-For` header ([cb0bc5d](https://github.com/dropseed/plain/commit/cb0bc5d08f))
- Improved `print_event` CLI output styling with dimmed text for less visual noise ([b09edfd](https://github.com/dropseed/plain/commit/b09edfd2a1))

### Upgrade instructions

- No changes required

## [0.91.0](https://github.com/dropseed/plain/releases/plain@0.91.0) (2025-11-24)

### What's changed

- Request body parsing refactored: the `request.data` attribute has been replaced with `request.json_data` and `request.form_data` for explicit content-type handling ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- `QueryDict` now has proper type annotations for `get()`, `pop()`, `getlist()`, and `__getitem__()` methods that reflect string return types ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- Forms now automatically select between `json_data` and `form_data` based on request content-type ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- View mixins `ObjectTemplateViewMixin` removed in favor of class inheritance for better typing - `UpdateView` and `DeleteView` now inherit from `DetailView` ([569afd6](https://github.com/dropseed/plain/commit/569afd606d))
- `AppLogger` context logging now uses a `context` dict parameter instead of `**kwargs` for better type checking ([581b406](https://github.com/dropseed/plain/commit/581b4060d3))
- Removed erroneous `AuthViewMixin` export from `plain.views` ([334bbb6](https://github.com/dropseed/plain/commit/334bbb6e7a))

### Upgrade instructions

- Replace `request.data` with the appropriate method:
    - For JSON requests: use `request.json_data` (returns a dict, raises `BadRequest` for invalid JSON)
    - For form data: use `request.form_data` (returns a `QueryDict`)
- Update `app_logger` calls that pass context as kwargs to use the `context` parameter:

    ```python
    # Before
    app_logger.info("Message", user_id=123, action="login")

    # After
    app_logger.info("Message", context={"user_id": 123, "action": "login"})
    ```

## [0.90.0](https://github.com/dropseed/plain/releases/plain@0.90.0) (2025-11-20)

### What's changed

- Improved type annotations in `timezone.py`: `is_aware()` and `is_naive()` now accept both `datetime` and `time` objects for more flexible type checking ([a43145e](https://github.com/dropseed/plain/commit/a43145e697))
- Enhanced type annotations in view classes: `convert_value_to_response()` and handler result variables now use more explicit type hints for better IDE support ([dc4454e](https://github.com/dropseed/plain/commit/dc4454e196))
- Fixed type errors in forms and server workers: URL field now handles bytes properly, and worker wait_fds has explicit type annotation ([fc98d66](https://github.com/dropseed/plain/commit/fc98d666d4))

### Upgrade instructions

- No changes required

## [0.89.0](https://github.com/dropseed/plain/releases/plain@0.89.0) (2025-11-14)

### What's changed

- Improved type annotations in view classes: `url_args`, `url_kwargs`, and various template/form context dictionaries now have more specific type hints for better IDE support and type checking ([83bcb95](https://github.com/dropseed/plain/commit/83bcb95b09))

### Upgrade instructions

- No changes required

## [0.88.0](https://github.com/dropseed/plain/releases/plain@0.88.0) (2025-11-13)

### What's changed

- The `plain.forms` module now uses explicit imports instead of wildcard imports, improving IDE autocomplete and type checking support ([eff36f3](https://github.com/dropseed/plain/commit/eff36f31e8e15f84e11164a44c833aeab096ffbd))

### Upgrade instructions

- No changes required

## [0.87.0](https://github.com/dropseed/plain/releases/plain@0.87.0) (2025-11-12)

### What's changed

- Internal classes now use abstract base classes with `@abstractmethod` decorators instead of raising `NotImplementedError`, improving type checking and IDE support ([91b329a](https://github.com/dropseed/plain/commit/91b329a8adb477031c4358e638b12f35f19bb85d), [81b5f88](https://github.com/dropseed/plain/commit/81b5f88a4bd39785f6b19c3c00c0ed23a36fb72f), [d2e2423](https://github.com/dropseed/plain/commit/d2e24235f497a92f45d5a21fc83d802897c2dec0), [61e7b5a](https://github.com/dropseed/plain/commit/61e7b5a0c8675aaaf65f0a626ff7959a786dca7f))
- Updated to latest version of `ty` type checker and fixed type errors and warnings throughout the codebase ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa929058be517cb1d4ab35bd73a89f26b8))

### Upgrade instructions

- No changes required

## [0.86.2](https://github.com/dropseed/plain/releases/plain@0.86.2) (2025-11-11)

### What's changed

- CLI color output is now enabled in CI environments by checking the `CI` environment variable, matching the behavior of modern tools like uv ([a1500f15ed](https://github.com/dropseed/plain/commit/a1500f15ed))

### Upgrade instructions

- No changes required

## [0.86.1](https://github.com/dropseed/plain/releases/plain@0.86.1) (2025-11-10)

### What's changed

- The `plain preflight` command now outputs to stderr only when using `--format json`, keeping stdout clean for JSON parsing while avoiding success messages appearing in error logs for text format ([72ebee7729](https://github.com/dropseed/plain/commit/72ebee7729))
- CLI color handling now follows the CLICOLOR standard with proper priority: `NO_COLOR` > `CLICOLOR_FORCE`/`FORCE_COLOR` > `CLICOLOR` > `isatty` ([c7fea406c5](https://github.com/dropseed/plain/commit/c7fea406c5))

### Upgrade instructions

- No changes required

## [0.86.0](https://github.com/dropseed/plain/releases/plain@0.86.0) (2025-11-10)

### What's changed

- Log output is now split by severity level: INFO and below go to stdout, WARNING and above go to stderr for proper cloud platform log classification ([52403b15ba](https://github.com/dropseed/plain/commit/52403b15ba))
- Added `LOG_STREAM` setting to customize log output behavior with options: `"split"` (default), `"stdout"`, or `"stderr"` ([52403b15ba](https://github.com/dropseed/plain/commit/52403b15ba))
- Log configuration documentation expanded with detailed guidance on output streams and environment variable settings ([52403b15ba](https://github.com/dropseed/plain/commit/52403b15ba))

### Upgrade instructions

- No changes required (default behavior splits logs to stdout/stderr automatically, but this can be customized via `PLAIN_LOG_STREAM` environment variable if needed)

## [0.85.0](https://github.com/dropseed/plain/releases/plain@0.85.0) (2025-11-03)

### What's changed

- CLI help output now organizes commands into "Common Commands", "Core Commands", and "Package Commands" sections for better discoverability ([73d3a48](https://github.com/dropseed/plain/commit/73d3a48fca))
- CLI help output has been customized with improved formatting and shortcut indicators showing which commands are shortcuts (e.g., `migrate → models migrate`) ([db882e6](https://github.com/dropseed/plain/commit/db882e6d47))
- CSRF exception messages now include more detailed context about what was rejected and why (e.g., port mismatches, host mismatches) ([9a8e09c](https://github.com/dropseed/plain/commit/9a8e09c1dc))
- The `plain agent md` command now saves a combined `AGENTS.md` file to `.plain/` by default when using `plain dev`, making it easier to provide context to coding agents ([786b7a0](https://github.com/dropseed/plain/commit/786b7a0ca1))
- CLI help text styling has been refined with dimmed descriptions and usage prefixes for improved readability ([d7f7053](https://github.com/dropseed/plain/commit/d7f705398d))

### Upgrade instructions

- No changes required

## [0.84.1](https://github.com/dropseed/plain/releases/plain@0.84.1) (2025-10-31)

### What's changed

- Added `license = "BSD-3-Clause"` to package metadata in `pyproject.toml` ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.84.0](https://github.com/dropseed/plain/releases/plain@0.84.0) (2025-10-29)

### What's changed

- The `DEFAULT_RESPONSE_HEADERS` setting now supports format string placeholders (e.g., `{request.csp_nonce}`) for dynamic header values instead of requiring a callable function ([5199383128](https://github.com/dropseed/plain/commit/5199383128))
- Views can now set headers to `None` to explicitly remove default response headers ([5199383128](https://github.com/dropseed/plain/commit/5199383128))
- Added comprehensive documentation for customizing default response headers including override, remove, and extend patterns ([5199383128](https://github.com/dropseed/plain/commit/5199383128))

### Upgrade instructions

- If you have `DEFAULT_RESPONSE_HEADERS` configured as a callable function, convert it to a dictionary with format string placeholders:

    ```python
    # Before:
    def DEFAULT_RESPONSE_HEADERS(request):
        nonce = request.csp_nonce
        return {
            "Content-Security-Policy": f"script-src 'self' 'nonce-{nonce}'",
        }

    # After:
    DEFAULT_RESPONSE_HEADERS = {
        "Content-Security-Policy": "script-src 'self' 'nonce-{request.csp_nonce}'",
    }
    ```

- If you were overriding default headers to empty strings (`""`) to remove them, change those to `None` instead

## [0.83.0](https://github.com/dropseed/plain/releases/plain@0.83.0) (2025-10-29)

### What's changed

- Added comprehensive Content Security Policy (CSP) documentation explaining how to use nonces with inline scripts and styles ([784f3dd972](https://github.com/dropseed/plain/commit/784f3dd972))
- The `json_script` utility function now accepts an optional `nonce` parameter for CSP-compliant inline JSON scripts ([784f3dd972](https://github.com/dropseed/plain/commit/784f3dd972))

### Upgrade instructions

- Any `|json_script` usages need to make sure the second argument is a nonce, not a custom encoder (which is now third)

## [0.82.0](https://github.com/dropseed/plain/releases/plain@0.82.0) (2025-10-29)

### What's changed

- The `DEFAULT_RESPONSE_HEADERS` setting can now be a callable that accepts a request argument, enabling dynamic header generation per request ([cb92905834](https://github.com/dropseed/plain/commit/cb92905834))
- Added `request.csp_nonce` cached property for generating Content Security Policy nonces ([75071dcc70](https://github.com/dropseed/plain/commit/75071dcc70))
- Simplified the preflight command by moving `plain preflight check` back to `plain preflight` ([40c2c4560e](https://github.com/dropseed/plain/commit/40c2c4560e))

### Upgrade instructions

- If you use `plain preflight check`, update to `plain preflight` (the `check` subcommand has been removed for simplicity)
- If you use `plain preflight check --deploy`, update to `plain preflight --deploy`

## [0.81.0](https://github.com/dropseed/plain/releases/plain@0.81.0) (2025-10-22)

### What's changed

- Removed support for category-specific error template fallbacks like `4xx.html` and `5xx.html` ([9513f7c4fa](https://github.com/dropseed/plain/commit/9513f7c4fa))

### Upgrade instructions

- If you have `4xx.html` or `5xx.html` error templates, rename them to specific status code templates (e.g., `404.html`, `500.html`) or remove them if you prefer the plain HTTP response fallback

## [0.80.0](https://github.com/dropseed/plain/releases/plain@0.80.0) (2025-10-22)

### What's changed

- CSRF failures now raise `SuspiciousOperation` (HTTP 400) instead of `PermissionDenied` (HTTP 403) ([ad146bde3e](https://github.com/dropseed/plain/commit/ad146bde3e))
- Error templates can now use category-specific fallbacks like `4xx.html` or `5xx.html` instead of the generic `error.html` ([716cfa3cfc](https://github.com/dropseed/plain/commit/716cfa3cfc))
- Updated error template documentation with best practices for self-contained `500.html` templates ([55cea3b522](https://github.com/dropseed/plain/commit/55cea3b522))

### Upgrade instructions

- If you have a `templates/error.html` template, instead create specific error templates for each status code you want to customize (e.g., `400.html`, `403.html`, `404.html`, `500.html`). You can also create category-specific templates like `4xx.html` or `5xx.html` for broader coverage.

## [0.79.0](https://github.com/dropseed/plain/releases/plain@0.79.0) (2025-10-22)

### What's changed

- Response objects now have an `exception` attribute that stores the exception that caused 5xx errors ([0a243ba89c](https://github.com/dropseed/plain/commit/0a243ba89c))
- Middleware classes now use an abstract base class `HttpMiddleware` with a `process_request()` method ([b960eed6c6](https://github.com/dropseed/plain/commit/b960eed6c6))
- CSRF middleware now raises `PermissionDenied` instead of rendering a custom `CsrfFailureView` ([d4b93e59b3](https://github.com/dropseed/plain/commit/d4b93e59b3))
- The `HTTP_ERROR_VIEWS` setting has been removed ([7a4e3a31f4](https://github.com/dropseed/plain/commit/7a4e3a31f4))
- Standalone `plain-changelog` and `plain-upgrade` executables have been removed in favor of the built-in commands ([07c3a4c540](https://github.com/dropseed/plain/commit/07c3a4c540))
- Standalone `plain-build` executable has been removed ([99301ea797](https://github.com/dropseed/plain/commit/99301ea797))
- Removed automatic logging of all HTTP 400+ status codes for cleaner logs ([c2769d7281](https://github.com/dropseed/plain/commit/c2769d7281))

### Upgrade instructions

- If you have custom middleware, inherit from `HttpMiddleware` and rename your `__call__()` method to `process_request()`:

    ```python
    # Before:
    class MyMiddleware:
        def __init__(self, get_response):
            self.get_response = get_response

        def __call__(self, request):
            response = self.get_response(request)
            return response

    # After:
    from plain.http import HttpMiddleware

    class MyMiddleware(HttpMiddleware):
        def process_request(self, request):
            response = self.get_response(request)
            return response
    ```

- Remove any custom `HTTP_ERROR_VIEWS` setting from your configuration - error views are now controlled entirely by exception handlers
- If you were calling `plain-changelog` or `plain-upgrade` as standalone commands, use `plain changelog` or `plain upgrade` instead
- If you were calling `plain-build` as a standalone command, use `plain build` instead

## [0.78.2](https://github.com/dropseed/plain/releases/plain@0.78.2) (2025-10-20)

### What's changed

- Updated package metadata to use `[dependency-groups]` instead of `[tool.uv]` for development dependencies, following PEP 735 standard ([1b43a3a272](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.78.1](https://github.com/dropseed/plain/releases/plain@0.78.1) (2025-10-17)

### What's changed

- Fixed job worker logging by using `getLogger` instead of directly instantiating `Logger` for the plain logger ([dd675666b9](https://github.com/dropseed/plain/commit/dd675666b9))

### Upgrade instructions

- No changes required

## [0.78.0](https://github.com/dropseed/plain/releases/plain@0.78.0) (2025-10-17)

### What's changed

- Chores have been refactored to use abstract base classes instead of decorated functions ([c4466d3c60](https://github.com/dropseed/plain/commit/c4466d3c60))
- Added `SHELL_IMPORT` setting to customize what gets automatically imported in `plain shell` ([9055f59c08](https://github.com/dropseed/plain/commit/9055f59c08))
- Views that return `None` now raise `Http404` instead of returning `ResponseNotFound` ([5bb60016eb](https://github.com/dropseed/plain/commit/5bb60016eb))
- The `plain chores list` command output formatting now matches the `plain jobs list` format ([4b6881a49e](https://github.com/dropseed/plain/commit/4b6881a49e))

### Upgrade instructions

- Update any chores from decorated functions to class-based chores:

    ```python
    # Before:
    @register_chore("group")
    def chore_name():
        """Description"""
        return "Done!"

    # After:
    from plain.chores import Chore, register_chore

    @register_chore
    class ChoreName(Chore):
        """Description"""

        def run(self):
            return "Done!"
    ```

- Import `Chore` base class from `plain.chores` when creating new chores

## [0.77.0](https://github.com/dropseed/plain/releases/plain@0.77.0) (2025-10-13)

### What's changed

- The `plain server --reload` now uses `watchfiles` for improved cross-platform file watching ([92e95c5032](https://github.com/dropseed/plain/commit/92e95c5032))
- Server reloader now watches `.env*` files for changes and triggers automatic reload ([92e95c5032](https://github.com/dropseed/plain/commit/92e95c5032))
- HTML template additions and deletions now trigger automatic server reload when using `--reload` ([f2f31c288b](https://github.com/dropseed/plain/commit/f2f31c288b))
- Internal server worker type renamed from "gthread" to "thread" for clarity ([6470748e91](https://github.com/dropseed/plain/commit/6470748e91))

### Upgrade instructions

- No changes required

## [0.76.0](https://github.com/dropseed/plain/releases/plain@0.76.0) (2025-10-12)

### What's changed

- Added new `plain server` command with built-in WSGI server (vendored gunicorn) ([f9dc2867c7](https://github.com/dropseed/plain/commit/f9dc2867c7))
- The `plain server` command supports `WEB_CONCURRENCY` environment variable for worker processes ([0c3e8c6f32](https://github.com/dropseed/plain/commit/0c3e8c6f32))
- Simplified server startup logging to use a single consolidated log line ([b1405b71f0](https://github.com/dropseed/plain/commit/b1405b71f0))
- Removed `gunicorn` as an external dependency - server functionality is now built into plain core ([cb6c2f484d](https://github.com/dropseed/plain/commit/cb6c2f484d))
- Internal server environment variables renamed from `GUNICORN_*` to `PLAIN_SERVER_*` ([745c073123](https://github.com/dropseed/plain/commit/745c073123))
- Removed unused server features including hooks, syslog, proxy protocol, user/group dropping, and config file loading ([be0f82d92b](https://github.com/dropseed/plain/commit/be0f82d92b), [10c206875b](https://github.com/dropseed/plain/commit/10c206875b), [ecf327014c](https://github.com/dropseed/plain/commit/ecf327014c), [fb5a10f50b](https://github.com/dropseed/plain/commit/fb5a10f50b))

### Upgrade instructions

- Replace any direct usage of `gunicorn` with the new `plain server` command (ex. `gunicorn plain.wsgi:app --workers 4` becomes `plain server --workers 4`)
- Update any deployment scripts or Procfiles that use `gunicorn` to use `plain server` instead
- Remove `gunicorn` from your project dependencies if you added it separately (it's now built into plain)
- For Heroku deployments, the `$PORT` is not automatically detected - update your Procfile to `web: plain server --bind 0.0.0.0:$PORT`
- If you were using gunicorn configuration files, migrate the settings to `plain server` command-line options (run `plain server --help` to see available options)

## [0.75.0](https://github.com/dropseed/plain/releases/plain@0.75.0) (2025-10-10)

### What's changed

- Documentation references updated from `plain-worker` to `plain-jobs` following the package rename ([24219856e0](https://github.com/dropseed/plain/commit/24219856e0))

### Upgrade instructions

- No changes required

## [0.74.0](https://github.com/dropseed/plain/releases/plain@0.74.0) (2025-10-08)

### What's changed

- The `plain agent request` command now displays request ID in the response output ([4a20cfa3fc](https://github.com/dropseed/plain/commit/4a20cfa3fc))
- Request headers are now included in OpenTelemetry tracing baggage for improved observability ([08a3376d06](https://github.com/dropseed/plain/commit/08a3376d06))

### Upgrade instructions

- No changes required

## [0.73.0](https://github.com/dropseed/plain/releases/plain@0.73.0) (2025-10-07)

### What's changed

- Internal preflight result handling updated to use `model_options` instead of `_meta` for model label retrieval ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.72.2](https://github.com/dropseed/plain/releases/plain@0.72.2) (2025-10-06)

### What's changed

- Improved type annotations for test client responses with new `ClientResponse` wrapper class ([369353f9d6](https://github.com/dropseed/plain/commit/369353f9d6))
- Enhanced internal type checking for WSGI handler and request/response types ([50463b00c3](https://github.com/dropseed/plain/commit/50463b00c3))

### Upgrade instructions

- No changes required

## [0.72.1](https://github.com/dropseed/plain/releases/plain@0.72.1) (2025-10-02)

### What's changed

- Fixed documentation examples to use the correct view attribute names (`self.user` instead of `self.request.user`) ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.72.0](https://github.com/dropseed/plain/releases/plain@0.72.0) (2025-10-02)

### What's changed

- Request attributes `user` and `session` are no longer set directly on the request object ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- Test client now uses `plain.auth.requests.get_request_user()` to retrieve user for response object when available ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- Removed `plain.auth.middleware.AuthenticationMiddleware` from default middleware configuration ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- No changes required

## [0.71.0](https://github.com/dropseed/plain/releases/plain@0.71.0) (2025-09-30)

### What's changed

- Renamed `HttpRequest` to `Request` throughout the codebase for consistency and simplicity ([cd46ff20](https://github.com/dropseed/plain/commit/cd46ff2003))
- Renamed `HttpHeaders` to `RequestHeaders` for naming consistency ([cd46ff20](https://github.com/dropseed/plain/commit/cd46ff2003))
- Renamed settings: `APP_NAME` → `NAME`, `APP_VERSION` → `VERSION`, `APP_LOG_LEVEL` → `LOG_LEVEL`, `APP_LOG_FORMAT` → `LOG_FORMAT`, `PLAIN_LOG_LEVEL` → `FRAMEWORK_LOG_LEVEL` ([4c5f2166](https://github.com/dropseed/plain/commit/4c5f2166c1))
- Added `request.get_preferred_type()` method to select the most preferred media type from Accept header ([b105ba4d](https://github.com/dropseed/plain/commit/b105ba4dd0))
- Moved helper functions in `http/request.py` to be static methods of `QueryDict` ([0e1b0133](https://github.com/dropseed/plain/commit/0e1b0133c5))

### Upgrade instructions

- Replace all imports and usage of `HttpRequest` with `Request`
- Replace all imports and usage of `HttpHeaders` with `RequestHeaders`
- Update any custom settings that reference `APP_NAME` to `NAME`, `APP_VERSION` to `VERSION`, `APP_LOG_LEVEL` to `LOG_LEVEL`, `APP_LOG_FORMAT` to `LOG_FORMAT`, and `PLAIN_LOG_LEVEL` to `FRAMEWORK_LOG_LEVEL`
- Configuring these settings via the `PLAIN_` prefixed environment variable will need to be updated accordingly

## [0.70.0](https://github.com/dropseed/plain/releases/plain@0.70.0) (2025-09-30)

### What's changed

- Added comprehensive type annotations throughout the codebase for improved IDE support and type checking ([365414c](https://github.com/dropseed/plain/commit/365414cc6f))
- The `Asset` class in `plain.assets.finders` is now a module-level public class instead of being defined inside `iter_assets()` ([6321765](https://github.com/dropseed/plain/commit/6321765d30))

### Upgrade instructions

- No changes required

## [0.69.0](https://github.com/dropseed/plain/releases/plain@0.69.0) (2025-09-29)

### What's changed

- Model-related exceptions (`FieldDoesNotExist`, `FieldError`, `ObjectDoesNotExist`, `MultipleObjectsReturned`, `EmptyResultSet`, `FullResultSet`) moved from `plain.exceptions` to `plain.models.exceptions` ([1c02564](https://github.com/dropseed/plain/commit/1c02564561))
- Added `plain dev` alias prompt that suggests adding `p` as a shell alias for convenience ([d913b44](https://github.com/dropseed/plain/commit/d913b44fab))

### Upgrade instructions

- Replace imports of `FieldDoesNotExist`, `FieldError`, `ObjectDoesNotExist`, `MultipleObjectsReturned`, `EmptyResultSet`, or `FullResultSet` from `plain.exceptions` to `plain.models.exceptions`
- If you're using `ObjectDoesNotExist` in views, update your import from `plain.exceptions.ObjectDoesNotExist` to `plain.models.exceptions.ObjectDoesNotExist`

## [0.68.1](https://github.com/dropseed/plain/releases/plain@0.68.1) (2025-09-25)

### What's changed

- Preflight checks are now sorted by name for consistent ordering ([cb8e160](https://github.com/dropseed/plain/commit/cb8e160934))

### Upgrade instructions

- No changes required

## [0.68.0](https://github.com/dropseed/plain/releases/plain@0.68.0) (2025-09-25)

### What's changed

- Major refactor of the preflight check system with new CLI commands and improved output ([b0b610d461](https://github.com/dropseed/plain/commit/b0b610d461))
- Preflight checks now use descriptive IDs instead of numeric codes ([cd96c97b25](https://github.com/dropseed/plain/commit/cd96c97b25))
- Unified preflight error messages and hints into a single `fix` field ([c7cde12149](https://github.com/dropseed/plain/commit/c7cde12149))
- Added `plain-upgrade` as a standalone command for upgrading Plain packages ([42f2eed80c](https://github.com/dropseed/plain/commit/42f2eed80c))

### Upgrade instructions

- Update any uses of the `plain preflight` command to `plain preflight check`, and remove the `--database` and `--fail-level` options which no longer exist
- Custom preflight checks should be class based, extending `PreflightCheck` and implementing the `run()` method
- Preflight checks need to be registered with a custom name (ex. `@register_check("app.my_custom_check")`) and optionally with `deploy=True` if it should run in only in deploy mode
- Preflight results should use `PreflightResult` (optionally with `warning=True`) instead of `preflight.Warning` or `preflight.Error`
- Preflight result IDs should be descriptive strings (e.g., `models.lazy_reference_resolution_failed`) instead of numeric codes
- `PREFLIGHT_SILENCED_CHECKS` setting has been replaced with `PREFLIGHT_SILENCED_RESULTS` which should contain a list of result IDs to silence. `PREFLIGHT_SILENCED_CHECKS` now silences entire checks by name.

## [0.67.0](https://github.com/dropseed/plain/releases/plain@0.67.0) (2025-09-22)

### What's changed

- `ALLOWED_HOSTS` now defaults to `[]` (empty list) which allows all hosts, making it easier for development setups ([d3cb7712b9](https://github.com/dropseed/plain/commit/d3cb7712b9))
- Empty `ALLOWED_HOSTS` in production now triggers a preflight error instead of a warning to ensure proper security configuration ([d3cb7712b9](https://github.com/dropseed/plain/commit/d3cb7712b9))

### Upgrade instructions

- No changes required

## [0.66.0](https://github.com/dropseed/plain/releases/plain@0.66.0) (2025-09-22)

### What's changed

- Host validation moved to dedicated middleware and `ALLOWED_HOSTS` setting is now required ([6a4b7be](https://github.com/dropseed/plain/commit/6a4b7be220))
- Changed `request.get_port()` method to `request.port` cached property ([544f3e1](https://github.com/dropseed/plain/commit/544f3e19f8))
- Removed internal `request._get_full_path()` method ([50cdb58](https://github.com/dropseed/plain/commit/50cdb58d4e))

### Upgrade instructions

- Add `ALLOWED_HOSTS` setting to your configuration if not already present (required for host validation)
- Replace any usage of `request.get_host()` with `request.host`
- Replace any usage of `request.get_port()` with `request.port`

## [0.65.1](https://github.com/dropseed/plain/releases/plain@0.65.1) (2025-09-22)

### What's changed

- Fixed DisallowedHost exception handling in request span attributes to prevent telemetry errors ([bcc0005](https://github.com/dropseed/plain/commit/bcc000575b))
- Removed cached property optimization for scheme/host to improve request processing reliability ([3a52690](https://github.com/dropseed/plain/commit/3a52690d47))

### Upgrade instructions

- No changes required

## [0.65.0](https://github.com/dropseed/plain/releases/plain@0.65.0) (2025-09-22)

### What's changed

- Added CIDR notation support to `ALLOWED_HOSTS` for IP address range validation ([c485d21](https://github.com/dropseed/plain/commit/c485d21a8b))

### Upgrade instructions

- No changes required

## [0.64.0](https://github.com/dropseed/plain/releases/plain@0.64.0) (2025-09-19)

### What's changed

- Added `plain-build` command as a standalone executable ([4b39ca4](https://github.com/dropseed/plain/commit/4b39ca4599))
- Removed `constant_time_compare` utility function in favor of `hmac.compare_digest` ([55f3f55](https://github.com/dropseed/plain/commit/55f3f5596d))
- CLI now forces colors in CI environments (GitHub Actions, GitLab CI, etc.) for better output visibility ([56f7d2b](https://github.com/dropseed/plain/commit/56f7d2b312))

### Upgrade instructions

- Replace any usage of `plain.utils.crypto.constant_time_compare` with `hmac.compare_digest` or `secrets.compare_digest`

## [0.63.0](https://github.com/dropseed/plain/releases/plain@0.63.0) (2025-09-12)

### What's changed

- Model manager attribute renamed from `objects` to `query` throughout codebase ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Simplified HTTPS redirect middleware by removing `HTTPS_REDIRECT_EXEMPT_PATHS` and `HTTPS_REDIRECT_HOST` settings ([d264cd3](https://github.com/dropseed/plain/commit/d264cd306b))
- Database backups are now created automatically during migrations when `DEBUG=True` unless explicitly disabled ([c802307](https://github.com/dropseed/plain/commit/c8023074e9))

### Upgrade instructions

- Remove any `HTTPS_REDIRECT_EXEMPT_PATHS` and `HTTPS_REDIRECT_HOST` settings from your configuration - the HTTPS redirect middleware now performs a blanket redirect. For advanced redirect logic, write custom middleware.

## [0.62.1](https://github.com/dropseed/plain/releases/plain@0.62.1) (2025-09-09)

### What's changed

- Added clarification about `app_logger.kv` removal to 0.62.0 changelog ([106636f](https://github.com/dropseed/plain/commit/106636fca6))

### Upgrade instructions

- No changes required

## [0.62.0](https://github.com/dropseed/plain/releases/plain@0.62.0) (2025-09-09)

### What's changed

- Complete rewrite of logging settings and AppLogger with improved formatters and debug capabilities ([ea7c953](https://github.com/dropseed/plain/commit/ea7c9537e3))
- Added `app_logger.debug_mode()` context manager to temporarily change log level ([f535459](https://github.com/dropseed/plain/commit/f53545f9fa))
- Minimum Python version updated to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Removed `app_logger.kv` in favor of context kwargs ([ea7c953](https://github.com/dropseed/plain/commit/ea7c9537e3))

### Upgrade instructions

- Make sure you are using Python 3.13 or higher
- Replace any `app_logger.kv.info("message", key=value)` calls with `app_logger.info("message", key=value)` or appropriate log level

## [0.61.0](https://github.com/dropseed/plain/releases/plain@0.61.0) (2025-09-03)

### What's changed

- Added new `plain agent` command with subcommands for coding agents including `docs`, `md`, and `request` ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))
- Added `-c` option to `plain shell` to execute commands and exit, similar to `python -c` ([5e67f0b](https://github.com/dropseed/plain/commit/5e67f0bcd8))
- The `plain docs --llm` functionality has been moved to `plain agent docs` command ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))
- Removed the `plain help` command in favor of standard `plain --help` ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))

### Upgrade instructions

- Replace `plain docs --llm` usage with `plain agent docs` command
- Use `plain --help` instead of `plain help` command

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
- Replace any QuerySet filters using `pk` with `id` (e.g., `Model.query.get(pk=1)` becomes `Model.query.get(id=1)`)

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
