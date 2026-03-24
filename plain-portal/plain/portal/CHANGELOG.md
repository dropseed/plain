# plain-portal changelog

## [0.2.0](https://github.com/dropseed/plain/releases/plain-portal@0.2.0) (2026-03-24)

### What's changed

- **Simplified `portal connect`** — now runs in the foreground instead of forking a background daemon. Kill the process to end the session ([95be9f59e68a](https://github.com/dropseed/plain/commit/95be9f59e68a))
- Removed `portal disconnect` and `portal status` commands — no longer needed since connect runs in the foreground ([95be9f59e68a](https://github.com/dropseed/plain/commit/95be9f59e68a))
- Removed PID file tracking and `--foreground` flag ([95be9f59e68a](https://github.com/dropseed/plain/commit/95be9f59e68a))
- Updated agent skill to reflect foreground-only connect workflow ([669e52eda37d](https://github.com/dropseed/plain/commit/669e52eda37d))

### Upgrade instructions

- `plain portal connect` now runs in the foreground — kill the process (Ctrl+C) to disconnect instead of running `plain portal disconnect`.
- Remove any scripts or automation that use `plain portal disconnect` or `plain portal status`.

## [0.1.1](https://github.com/dropseed/plain/releases/plain-portal@0.1.1) (2026-03-23)

### What's changed

- Fix backgrounded `connect` on macOS by forking before entering asyncio, avoiding kqueue file descriptor issues ([870d591fb1cc](https://github.com/dropseed/plain/commit/870d591fb1cc))
- Simplify `local.py` by moving fork/daemonize logic into `cli.py` and removing the `foreground` parameter from the `connect()` function ([870d591fb1cc](https://github.com/dropseed/plain/commit/870d591fb1cc))

### Upgrade instructions

- No changes required.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-portal@0.1.0) (2026-03-22)

### What's changed

Initial release. Remote Python shell and file transfer via encrypted tunnel.

- SPAKE2 key exchange + NaCl SecretBox for E2E encryption through a Cloudflare relay ([7c782e15a962](https://github.com/dropseed/plain/commit/7c782e15a962))
- Streaming stdout — output appears line-by-line in real time
- Read-only database mode by default, `--writable` opt-in with confirmation prompt
- File transfer: `pull` and `push` through the encrypted tunnel (up to 50MB, push restricted to `/tmp/`)
- Per-command exec timeout (default 120s, `--timeout` override)
- `--json` flag for machine-readable exec output
- Keepalive pings every 30s to survive proxy idle timeouts
- CLI commands: `start`, `connect`, `exec`, `pull`, `push`, `disconnect`, `status`
