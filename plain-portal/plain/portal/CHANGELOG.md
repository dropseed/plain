# plain-portal changelog

## [0.2.5](https://github.com/dropseed/plain/releases/plain-portal@0.2.5) (2026-04-13)

### What's changed

- Migrated type suppression comments to `ty: ignore` for the new ty checker version. ([4ec631a7ef51](https://github.com/dropseed/plain/commit/4ec631a7ef51))

### Upgrade instructions

- No changes required.

## [0.2.4](https://github.com/dropseed/plain/releases/plain-portal@0.2.4) (2026-04-03)

### What's changed

- **Replaced socket-probe guard with `flock`-based locking.** The previous approach tried to connect to the existing socket to detect a running session, but this was racy and could fail under certain timing conditions. Now uses an exclusive file lock (`fcntl.flock`) that is held for the process lifetime and released automatically on exit or crash. ([a6866332a7cb](https://github.com/dropseed/plain/commit/a6866332a7cb))
- **Portal socket is now project-scoped.** The socket and lock files are placed under `.plain/tmp/portal/` instead of the system temp directory, so multiple projects can run portal sessions simultaneously without conflicts. ([a6866332a7cb](https://github.com/dropseed/plain/commit/a6866332a7cb))

### Upgrade instructions

- No changes required.

## [0.2.3](https://github.com/dropseed/plain/releases/plain-portal@0.2.3) (2026-04-02)

### What's changed

- Updated agent skill to include `--yes` flag alongside `--writable` in documentation, matching the confirmation-skip behavior added in 0.2.1 ([86b0257](https://github.com/dropseed/plain/commit/86b0257))

### Upgrade instructions

- No changes required.

## [0.2.2](https://github.com/dropseed/plain/releases/plain-portal@0.2.2) (2026-03-30)

### What's changed

- Detect stale socket files after SIGKILL instead of blocking new sessions — `connect` now probes the existing socket and cleans it up if nothing is listening, rather than refusing to start ([461da76c8c78](https://github.com/dropseed/plain/commit/461da76c8c78))
- Handle unclean websocket disconnects gracefully — remote sessions now catch `ConnectionClosed` instead of crashing when the relay or network drops the connection ([5b7995df2f6d](https://github.com/dropseed/plain/commit/5b7995df2f6d))
- Updated agent skill to clarify that both `start` and `connect` are blocking foreground processes ([6a6b1ccff532](https://github.com/dropseed/plain/commit/6a6b1ccff532))

### Upgrade instructions

- No changes required.

## [0.2.1](https://github.com/dropseed/plain/releases/plain-portal@0.2.1) (2026-03-27)

### What's changed

- Added `--yes`/`-y` flag to `portal start` to skip the write-mode confirmation prompt ([0af36e101f03](https://github.com/dropseed/plain/commit/0af36e101f03))

### Upgrade instructions

- No changes required.

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
