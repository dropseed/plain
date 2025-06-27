# plain-dev changelog

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
