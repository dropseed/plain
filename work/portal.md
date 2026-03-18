---
labels:
  - plain.cli
depends_on: models-read-only-transactions
---

# Portal: Remote Python shell and file transfer via encrypted tunnel

A way to open a Python shell on a remote machine (production dyno, container, VM) and send commands to it from your local machine — through an encrypted, ephemeral tunnel that requires only outbound connections on both sides. Also supports transferring files in both directions through the same tunnel.

## Why

Developers (and AI agents like Claude Code) need to explore production data, debug issues, and run one-off queries. Current options are bad:

- **`heroku run` per command** — 10-30s cold start, no state between commands
- **SSH/port forwarding** — platform-specific, different on every provider
- **HTTP endpoint on web process** — adds public attack surface to production
- **Direct DB connection** — loses access to app context (cache, env, services); code version mismatch risk

The portal approach: both sides make outbound WebSocket connections to a relay server, find each other via a short code, establish an E2E encrypted channel, and communicate through it. The remote side runs a Python REPL with the full app loaded.

## How it works

```
Production (heroku run, fly ssh, kubectl exec, etc.)     Local machine
┌──────────────────────┐                                  ┌──────────────────┐
│ plain portal start   │───── outbound WSS ────▶          │                  │
│                      │                       ┌────────┐ │ plain portal     │
│ Python REPL with     │◀═══ encrypted msgs ══▶│ Relay  │◀│ connect          │
│ app loaded, DB       │                       │ Server │ │ 7-crossword-     │
│ connected            │                       └────────┘ │ pineapple        │
└──────────────────────┘                                  └──────────────────┘
```

1. Remote side runs `plain portal start` — connects to relay, prints a short code (e.g. `7-crossword-pineapple`)
2. Local side runs `plain portal connect 7-crossword-pineapple` — connects to relay with the same code
3. SPAKE2 key exchange through the relay — both sides derive a shared secret from the human-readable code
4. All subsequent messages encrypted with nacl secretbox — relay never sees plaintext
5. Local side sends commands (`exec`, `pull`, `push`) through the persistent tunnel
6. Each `exec` runs in a fresh namespace — no state between commands
7. Session stays alive until `plain portal disconnect` or the remote side exits

## CLI usage

```bash
# On production (via whatever mechanism the platform provides)
heroku run plain portal start
fly ssh console -C "plain portal start"
kubectl exec -it deploy/myapp -- plain portal start

# Output:
# Portal code: 7-crossword-pineapple
# Waiting for connection...

# Or, pre-set the code so both sides can be started independently
heroku run plain portal start --code my-secret-phrase

# Locally — establish connection (backgrounds itself)
plain portal connect 7-crossword-pineapple
# → Connected to remote. Session active.

# Send commands through the open tunnel
plain portal exec "User.objects.count()"
# → 4827

plain portal exec "User.objects.filter(active=False).values('email')[:5]"
# → [{'email': 'a@b.com'}, {'email': 'b@c.com'}, ...]

# Transfer files
plain portal pull /tmp/export.csv ./export.csv
plain portal push ./fix.py /tmp/fix.py

# Tear down
plain portal disconnect
```

### Connection model

The local side uses a background process + Unix socket:

1. `plain portal connect <code>` — connects to relay, does SPAKE2 key exchange, then backgrounds itself and listens on a local Unix socket (`/tmp/plain-portal.sock`)
2. `exec`, `pull`, `push` — connect to the local Unix socket, send a request through the tunnel, print the response
3. `plain portal disconnect` — kills the background process, cleans up the socket

The tunnel connection stays open across commands, but each `exec` gets a **fresh Python namespace** on the remote side. No state carries over between commands — if you need setup, put it all in one code block. This keeps things simple and avoids state management / cleanup issues. (Users who want a stateful interactive REPL can just `heroku run plain shell` directly.)

`plain portal status` shows whether a session is active and connection info.

### Pre-set codes

By default, `start` generates a random code and prints it. But `--code <code>` lets both sides agree on a code upfront. This is useful when both sides are scripted independently or when a teammate starts the remote side for you.

In the common case — Claude Code driving both sides — this isn't needed. Claude runs `heroku run plain portal start`, reads the code from stdout, then runs `plain portal connect <code>` itself.

User-chosen codes are weaker than random ones, so the relay should enforce rate limiting on code guessing regardless.

## Read-only by default

The portal session uses a read-only database transaction by default (Postgres `SET TRANSACTION READ ONLY`). Any write attempt raises a database error.

```bash
# Read-only (default)
plain portal start

# Writable (explicit opt-in + confirmation prompt)
plain portal start --writable
# "⚠ This session allows writes to the production database. Continue? [y/N]"
```

Uses the same `connection.read_only` mechanism from psycopg3 proposed in `models-read-only-transactions`.

## Output format

Each `exec` captures both **stdout/stderr** from the execution and the **`repr()` of the last expression's value** (if any). Both are returned to the local side.

```bash
# Return value only (no print statements)
plain portal exec "User.objects.count()"
# → 4827

# Stdout only (no return value from a loop)
plain portal exec "for u in User.objects.all()[:3]: print(u.email)"
# a@example.com
# b@example.com
# c@example.com

# Both — stdout first, then return value
plain portal exec "
print('checking...')
User.objects.filter(active=False).count()
"
# checking...
# → 312

# Tracebacks on errors
plain portal exec "1/0"
# Traceback (most recent call last):
#   ...
# ZeroDivisionError: division by zero
```

A flag for JSON output when structured data is needed:

```bash
plain portal exec --json "User.objects.filter(active=False).values('email')[:5]"
```

## Relay server

Hosted at `portal.plainframework.com` on Cloudflare Workers + Durable Objects.

The relay is minimal:

- Each portal session = one Durable Object holding two WebSocket connections
- First connection arrives → store it, wait
- Second connection with same code arrives → pair them
- Forward encrypted messages between them
- Clean up when either disconnects

The relay never sees plaintext. It just passes encrypted bytes between two WebSocket connections.

## Crypto

- **Key exchange**: SPAKE2 — derives a shared secret from the human-readable code. Resistant to offline dictionary attacks (an eavesdropper can't brute-force the code from the transcript).
- **Encryption**: nacl secretbox (XSalsa20-Poly1305) — encrypt every message with the shared secret.
- **Libraries**: `spake2` and `pynacl` (both pure Python available, C extensions optional).

## Why not magic-wormhole?

The `magic-wormhole` library is designed for file transfer, not persistent bidirectional channels. The underlying crypto (SPAKE2 + nacl) is just two small libraries. The relay is a Cloudflare Durable Object we're writing anyway. Rolling our own is probably less code than adapting magic-wormhole.

## Remote-side activity log

The remote side logs all activity to its terminal as commands come in. The person who started the portal sees everything in real time:

```
Portal code: 7-crossword-pineapple
Waiting for connection...

[14:32:01] Connected from remote client.
[14:32:05] exec: User.objects.count()
           → 4827
[14:32:12] exec: User.objects.filter(active=False).values('email')[:5]
           → [{'email': 'a@b.com'}, ...]
[14:33:01] pull: /tmp/export.csv (12.4 KB)
[14:35:44] push: /tmp/fix.py (892 B)
[14:35:47] exec: exec(open('/tmp/fix.py').read())
           → None
[14:50:01] Client disconnected.
```

This is important for the **support use case**: a customer running a self-hosted app can open a portal and share the code with the developer. The developer connects remotely and debugs — but the customer watches the full session on their terminal. They can see every command executed, every file transferred, and can Ctrl-C to kill the session at any time.

The customer doesn't need to grant SSH access, open firewall ports, or share credentials. They just run `plain portal start`, share the code, and supervise. When they're done, they kill the process.

## Idle timeout

The remote side auto-disconnects after 30 minutes of inactivity (no commands received). On platforms like Heroku, the remote process is a one-off dyno billing by the minute — leaving it running indefinitely is wasteful. The timeout is configurable:

```bash
plain portal start --timeout 60  # 60 minutes
plain portal start --timeout 0   # no timeout (not recommended)
```

The remote side prints a warning before disconnecting. The local side detects the disconnect and cleans up.

## Security model

The portal doesn't add its own authorization layer. The security boundaries are:

1. **Platform access** — you need `heroku run` / `kubectl exec` / SSH access to start the remote side. If you can do that, you can already run `plain shell` directly.
2. **Portal code** — short-lived, random, with SPAKE2 protecting against eavesdropper brute-force.
3. **E2E encryption** — the relay never sees plaintext.

The portal is intentionally unrestricted (like `plain shell`) — it can run any Python code. The access control is "can you start the remote process?" If you can, you already have full access anyway.

`--writable` controls database write access only, not general code execution. Code can always read the filesystem, call APIs, etc. — just like a normal shell session.

## Platform compatibility

Works anywhere you can run a process — the only requirement is outbound internet access:

| Platform      | How to start the remote side                        |
| ------------- | --------------------------------------------------- |
| Heroku        | `heroku run plain portal start`                     |
| Fly.io        | `fly ssh console -C "plain portal start"`           |
| Kubernetes    | `kubectl exec -it deploy/app -- plain portal start` |
| Any VM/server | `ssh myserver plain portal start`                   |
| Docker        | `docker exec -it container plain portal start`      |

## File transfer

The encrypted tunnel already passes arbitrary bytes — file transfer is just another message type. Pull files from production or push files to it through the same portal connection.

```bash
# Pull a file from production to local
plain portal pull /tmp/export.csv ./export.csv

# Push a file from local to production
plain portal push ./fix_data.py /tmp/fix_data.py

# Combine with exec — generate a file remotely, then pull it
plain portal exec "
qs = User.objects.filter(active=False)
import csv
with open('/tmp/inactive.csv', 'w') as f:
    writer = csv.writer(f)
    writer.writerow(['email', 'date_joined'])
    for u in qs.values_list('email', 'date_joined'):
        writer.writerow(u)
"
plain portal pull /tmp/inactive.csv ./inactive.csv

# Push a script and run it
plain portal push ./backfill.py /tmp/backfill.py
plain portal exec "exec(open('/tmp/backfill.py').read())"
```

### Message protocol

Each message through the tunnel has a type envelope. File transfer adds two new types alongside `exec`:

```python
# Exec (existing)
{"type": "exec", "code": "User.objects.count()"}
{"type": "exec_result", "stdout": "", "return_value": "4827", "error": None}

# File pull (local requests a file from remote)
{"type": "file_pull", "remote_path": "/tmp/export.csv"}
{"type": "file_data", "name": "export.csv", "chunks": 3, "chunk": 0, "data": "<base64>"}

# File push (local sends a file to remote)
{"type": "file_push", "remote_path": "/tmp/fix.py", "chunks": 1, "chunk": 0, "data": "<base64>"}
{"type": "file_push_result", "path": "/tmp/fix.py", "bytes": 1234}
```

Large files are chunked so individual WebSocket messages stay small. The relay doesn't need any changes — it's still just forwarding encrypted bytes.

### Limits

- **Max file size**: 50MB per transfer — keeps relay memory bounded and avoids abuse. Production files larger than this should use a proper export pipeline.
- **`push` is always allowed**: `--writable` controls database writes, not filesystem access. Pushing a script to `/tmp/` and running it read-only is a valid use case.
- **Temp directory only**: By default, `push` only writes to `/tmp/`. A `--allow-any-path` flag on the remote side relaxes this.

## Open questions

- Code format: `number-word-word` like magic-wormhole? How many words for sufficient entropy vs. usability?
- Brute-force protection: rate limiting on the relay for code guessing?
- Truncation: cap output size for huge querysets? Or leave that to the user (`.[:10]`)?
- File transfer chunk size: 64KB? 256KB? Depends on Durable Object message limits.
- Should `pull` support globs or directories, or keep it single-file only?
