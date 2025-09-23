# plain-dev changelog

## [0.35.0](https://github.com/dropseed/plain/releases/plain-dev@0.35.0) (2025-09-22)

### What's changed

- Removed automatic `PLAIN_ALLOWED_HOSTS` configuration from the dev server as this is now handled by the core Plain framework ([d3cb771](https://github.com/dropseed/plain/commit/d3cb7712b9))

### Upgrade instructions

- No changes required

## [0.34.0](https://github.com/dropseed/plain/releases/plain-dev@0.34.0) (2025-09-19)

### What's changed

- Minimum Python version requirement increased from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Upgrade your Python environment to Python 3.13 or later

## [0.33.3](https://github.com/dropseed/plain/releases/plain-dev@0.33.3) (2025-09-03)

### What's changed

- Added retries to background service startup to improve reliability when services take longer to initialize ([e2b3a42](https://github.com/dropseed/plain/commit/e2b3a42313))

### Upgrade instructions

- No changes required

## [0.33.2](https://github.com/dropseed/plain/releases/plain-dev@0.33.2) (2025-08-22)

### What's changed

- The development localhost hostname is now automatically lowercased when generated from the pyproject.toml name ([4454f01](https://github.com/dropseed/plain/commit/4454f01787))
- Updated README with improved structure, table of contents, and better installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.33.1](https://github.com/dropseed/plain/releases/plain-dev@0.33.1) (2025-07-18)

### What's changed

- Dev services are no longer automatically started when running in CI environments unless explicitly enabled with `PLAIN_DEV_SERVICES_AUTO=true` ([b8452bae74](https://github.com/dropseed/plain/commit/b8452bae74))
- The `plain dev logs` command now skips automatic service startup to avoid conflicts ([ff65428bca](https://github.com/dropseed/plain/commit/ff65428bca))

### Upgrade instructions

- No changes required

## [0.33.0](https://github.com/dropseed/plain/releases/plain-dev@0.33.0) (2025-07-18)

### What's changed

- Added automatic background startup of dev services when running `plain dev` commands. Services defined in `pyproject.toml` will now start automatically ([0a5ffc6de5](https://github.com/dropseed/plain/commit/0a5ffc6de5)).
- Added `plain dev logs` command to view output from recent `plain dev` runs. Supports options like `--follow`, `--pid`, `--path`, and `--services` to manage and view different log outputs ([0a5ffc6de5](https://github.com/dropseed/plain/commit/0a5ffc6de5)).
- Added `--start` and `--stop` flags to both `plain dev` and `plain dev services` commands for running processes in the background. Use `plain dev --start` to launch the dev server in background mode and `plain dev --stop` to terminate it ([0a5ffc6de5](https://github.com/dropseed/plain/commit/0a5ffc6de5)).
- Improved process management with better PID tracking and graceful shutdown handling for both dev server and services ([0a5ffc6de5](https://github.com/dropseed/plain/commit/0a5ffc6de5)).
- Improved CLI error handling by using `click.UsageError` instead of manual error printing and `sys.exit()` ([88f06c5184](https://github.com/dropseed/plain/commit/88f06c5184)).
- Removed `psycopg[binary]` dependency from plain-dev as database drivers should be installed separately based on project needs ([63224001c9](https://github.com/dropseed/plain/commit/63224001c9)).

### Upgrade instructions

- No changes required

## [0.32.1](https://github.com/dropseed/plain/releases/plain-dev@0.32.1) (2025-06-27)

### What's changed

- Fixed an error when running `plain dev precommit` (or the `plain precommit` helper) that passed an extra `default` argument to `plain preflight --database`. The flag now correctly aligns with the current `plain preflight` CLI ([db65930](https://github.com/dropseed/plain/commit/db659304129a453676c0dcc20c13b606254ce1c2)).

### Upgrade instructions

- No changes required.

## [0.32.0](https://github.com/dropseed/plain/releases/plain-dev@0.32.0) (2025-06-23)

### What's changed

- `plain dev` now writes a PID file and will refuse to start if it detects that another `plain dev` instance is already running in the same project ([75b7a50](https://github.com/dropseed/plain/commit/75b7a505ae3c60675099ffd440f35cf8f30665da)).
- When no `--port` is provided, `plain dev` now checks if port 8443 is available and, if not, automatically selects the next free port. Supplying `--port` will error if that port is already in use ([3f5141f](https://github.com/dropseed/plain/commit/3f5141f54a65455f5784ed3f97be2d153ed10a23)).
- The development request-log UI has been removed for now, along with its related endpoints and templates ([8ac6f71](https://github.com/dropseed/plain/commit/8ac6f7170efa72e6069bae3cc91809b5fe0f8a7d)).
- `plain contrib --all` skips any installed `plainx-*` packages instead of erroring when it can’t locate their repository ([3a26aee](https://github.com/dropseed/plain/commit/3a26aee25e586a66e02a348aa24ee6e048ea0b71)).

### Upgrade instructions

- No changes required.
