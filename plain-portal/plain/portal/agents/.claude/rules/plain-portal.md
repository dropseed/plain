# Portal

Remote Python shell and file transfer via encrypted tunnel. Connects a local machine to a remote production server through a relay using SPAKE2 key exchange and NaCl encryption.

## CLI Commands

- `uv run plain portal start` — start a portal session on the remote machine (prints a portal code)
- `uv run plain portal connect <code>` — connect to a remote session from your local machine
- `uv run plain portal exec <code>` — execute Python code on the remote machine (`--json` for JSON output)
- `uv run plain portal pull <remote_path> <local_path>` — pull a file from the remote machine
- `uv run plain portal push <local_path> <remote_path>` — push a file to the remote machine (requires `--writable`)
- `uv run plain portal status` — show session status
- `uv run plain portal disconnect` — disconnect the active session

## Key Details

- Sessions are **read-only by default** — database writes require `--writable` flag on `start`
- File pushes are restricted to `/tmp/` on the remote machine — no delete command exists; the OS cleans up `/tmp/` naturally
- The portal code (e.g. `7-crossword-pineapple`) is never sent to the relay — only a SHA-256 hash is used as the channel ID
- `connect` backgrounds a daemon by default — use `--foreground` to keep it in the foreground
- Idle timeout defaults to 30 minutes (`--timeout 0` to disable)
