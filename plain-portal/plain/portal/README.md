# plain.portal

**Remote Python shell and file transfer via encrypted tunnel.**

- [Overview](#overview)
- [Quick start](#quick-start)
- [CLI reference](#cli-reference)
- [How it works](#how-it-works)
- [Read-only mode](#read-only-mode)
- [File transfer](#file-transfer)
- [Output](#output)
- [Security model](#security-model)
- [Platform compatibility](#platform-compatibility)
- [Relay server](#relay-server)
- [Activity log](#activity-log)
- [Installation](#installation)

## Overview

Plain Portal opens a Python shell on a remote machine -- production dyno, container, VM -- and lets you send commands to it from your local terminal through an encrypted, ephemeral tunnel. It also supports transferring files in both directions through the same connection.

Both sides make outbound WebSocket connections to a relay server, find each other via a short human-readable code, establish end-to-end encryption, and communicate through the tunnel. The remote side runs Python with the full app loaded and database connected.

**Why not just SSH or `heroku run`?**

- `heroku run` per command has 10-30s cold start and no state between invocations.
- SSH and port forwarding are platform-specific and configured differently on every provider.
- An HTTP debug endpoint adds public attack surface to production.
- A direct database connection loses app context (environment, services, model layer) and risks code version mismatch.

Portal requires only outbound internet access on both sides. No firewall rules, no SSH keys, no exposed ports.

## Quick start

**1. Start a session on the remote machine** (via whatever mechanism your platform provides):

```console
$ heroku run plain portal start
Portal code: 7-crossword-pineapple
Session mode: read-only
Waiting for connection...
```

**2. Connect from your local machine:**

```console
$ plain portal connect 7-crossword-pineapple
Connected to remote. Session active.
```

**3. Run commands through the tunnel:**

```console
$ plain portal exec "User.query.count()"
-> 4827

$ plain portal exec "User.query.filter(active=False).count()"
-> 312
```

**4. Disconnect when done:**

```console
$ plain portal disconnect
Portal session disconnected.
```

## CLI reference

### `plain portal start`

Start a portal session on the remote machine. Connects to the relay, prints a portal code, and waits for a local client to connect.

```console
$ plain portal start
$ plain portal start --writable
$ plain portal start --timeout 60
```

| Option       | Description                                      | Default         |
| ------------ | ------------------------------------------------ | --------------- |
| `--writable` | Allow database writes (prompts for confirmation) | Off (read-only) |
| `--timeout`  | Idle timeout in minutes (0 to disable)           | 30              |

### `plain portal connect <code>`

Connect to a remote portal session. Establishes the encrypted tunnel and backgrounds itself.

```console
$ plain portal connect 7-crossword-pineapple
$ plain portal connect 7-crossword-pineapple --foreground
```

| Option         | Description                                | Default |
| -------------- | ------------------------------------------ | ------- |
| `--foreground` | Run in foreground instead of backgrounding | Off     |

### `plain portal exec <code>`

Execute Python code on the remote machine. Requires an active connection.

```console
$ plain portal exec "User.query.count()"
$ plain portal exec --json "User.query.filter(active=False).values('email')[:5]"
```

| Option      | Description                        | Default |
| ----------- | ---------------------------------- | ------- |
| `--json`    | Serialize the return value as JSON | Off     |
| `--timeout` | Execution timeout in seconds       | 120     |

### `plain portal pull <remote_path> <local_path>`

Pull a file from the remote machine to your local machine.

```console
$ plain portal pull /tmp/export.csv ./export.csv
Pulled /tmp/export.csv -> ./export.csv (12400 bytes)
```

### `plain portal push <local_path> <remote_path>`

Push a file from your local machine to the remote machine. Writes are restricted to `/tmp/` on the remote side.

```console
$ plain portal push ./fix.py /tmp/fix.py
Pushed ./fix.py -> /tmp/fix.py (892 bytes)
```

### `plain portal disconnect`

Kill the background daemon and clean up the local session.

### `plain portal status`

Show whether a portal session is active and its process ID.

## How it works

```
Production (heroku run, fly ssh, kubectl exec, etc.)     Local machine
+----------------------+                                  +------------------+
| plain portal start   |----- outbound WSS ---->          |                  |
|                      |                       +--------+ | plain portal     |
| Python REPL with     |<=== encrypted msgs ==>| Relay  |<| connect          |
| app loaded, DB       |                       | Server | | 7-crossword-     |
| connected            |                       +--------+ | pineapple        |
+----------------------+                                  +------------------+
```

1. The remote side runs `plain portal start` -- connects to the relay via WebSocket and prints a short code (e.g. `7-crossword-pineapple`).
2. The local side runs `plain portal connect <code>` -- connects to the same relay with the matching code.
3. Both sides perform a SPAKE2 key exchange through the relay, deriving a shared secret from the human-readable code.
4. All subsequent messages are encrypted with NaCl SecretBox (XSalsa20-Poly1305). The relay never sees plaintext.
5. The local side sends commands (`exec`, `pull`, `push`) through the persistent tunnel.
6. Each `exec` runs in a fresh Python namespace -- no state carries over between commands.
7. Both sides send periodic keepalive pings every 30 seconds to keep the WebSocket connection alive through proxies and NATs.
8. The session stays alive until `plain portal disconnect` or the remote process exits.

### Connection model

The local side uses a background daemon and Unix socket:

- `plain portal connect <code>` establishes the WebSocket connection, performs the key exchange, then forks into the background and listens on a Unix socket (`/tmp/plain-portal.sock`).
- `exec`, `pull`, and `push` connect to the local Unix socket, send a request through the tunnel, and print the response.
- `plain portal disconnect` kills the background process and cleans up the socket.

The tunnel stays open across commands, but each `exec` gets a fresh Python namespace on the remote side. If you need setup code, put it all in one code block. Users who want a stateful interactive REPL should use `plain shell` directly on the remote machine.

### Encryption

- **Key exchange**: SPAKE2 -- a password-authenticated key exchange that derives a shared secret from the human-readable portal code. An eavesdropper observing the relay traffic cannot brute-force the code offline.
- **Message encryption**: NaCl SecretBox (XSalsa20-Poly1305) -- every message after the handshake is encrypted with the shared secret.
- **Channel ID**: The portal code is never sent to the relay. A SHA-256 hash of the code is used as the channel ID for pairing. The raw code is only used locally for SPAKE2.
- **Libraries**: `spake2` and `pynacl`.

## Read-only mode

By default, the remote session enforces a read-only database connection. Any INSERT, UPDATE, DELETE, or DDL statement raises a database error.

```console
$ plain portal start
```

To allow writes, pass `--writable`. This prompts for confirmation before starting:

```console
$ plain portal start --writable
This session allows writes to the production database. Continue? [y/N]
```

Read-only mode only restricts database writes. Code can still read the filesystem, call external APIs, and perform other non-database operations -- just like a normal shell session.

## File transfer

Pull files from production or push files to it through the same encrypted tunnel.

```console
# Pull a file from the remote machine
$ plain portal pull /tmp/export.csv ./export.csv

# Push a file to the remote machine (restricted to /tmp/)
$ plain portal push ./fix_data.py /tmp/fix_data.py
```

### Generate a file remotely, then pull it

```console
$ plain portal exec "
import csv
qs = User.query.filter(active=False)
with open('/tmp/inactive.csv', 'w') as f:
    writer = csv.writer(f)
    writer.writerow(['email', 'date_joined'])
    for u in qs.values_list('email', 'date_joined'):
        writer.writerow(u)
"

$ plain portal pull /tmp/inactive.csv ./inactive.csv
```

### Push a script and run it

```console
$ plain portal push ./backfill.py /tmp/backfill.py
$ plain portal exec "exec(open('/tmp/backfill.py').read())"
```

### Limits

- **Max file size**: 50 MB per transfer. Files are chunked into 256 KB messages so individual WebSocket frames stay small.
- **Push destination**: `push` only writes to `/tmp/` on the remote side. Attempts to write outside `/tmp/` are rejected.
- **`--writable` is independent**: `push` always works regardless of read-only mode. Pushing a script to `/tmp/` and running it read-only is a valid workflow.

## Output

### Streaming stdout

Stdout streams line-by-line in real time through the tunnel. Output from `print()` statements and other writes to stdout/stderr appears on the local side as it is produced, not buffered until the command finishes.

```console
$ plain portal exec "
import time
for i in range(5):
    print(f'Step {i}...')
    time.sleep(1)
"
Step 0...
Step 1...
Step 2...
Step 3...
Step 4...
```

Each line appears one second apart, as produced on the remote side.

### Exec timeout

Each `exec` has a timeout (default: 120 seconds). If the code runs longer, the command is interrupted and an error is returned. Override the timeout for long-running operations:

```console
$ plain portal exec --timeout 300 "run_slow_migration()"
```

The timeout is per-command, not per-session. Set it to `0` to disable.

### Output truncation

Return values over 1 MB are truncated. If you need to extract large data, write it to a file on the remote side and use `plain portal pull` to transfer it.

### JSON mode

Pass `--json` to get structured output for scripting and automation:

```console
$ plain portal exec --json "User.query.count()"
{"stdout": "", "return_value": "4827", "error": null}
```

When `--json` is set, the return value is serialized with `json.dumps` instead of `repr`. If JSON serialization fails, it falls back to `repr`.

### Human-readable mode

Without `--json`, output follows a human-readable format:

```console
# Return value only
$ plain portal exec "User.query.count()"
-> 4827

# Stdout from print statements
$ plain portal exec "for u in User.query.all()[:3]: print(u.email)"
a@example.com
b@example.com
c@example.com

# Both stdout and return value
$ plain portal exec "
print('checking...')
User.query.filter(active=False).count()
"
checking...
-> 312

# Tracebacks on errors
$ plain portal exec "1/0"
Traceback (most recent call last):
  ...
ZeroDivisionError: division by zero
```

## Security model

The portal does not add its own authorization layer. Security comes from three boundaries:

1. **Platform access** -- You need `heroku run`, `kubectl exec`, SSH, or equivalent access to start the remote side. If you can do that, you already have full shell access.
2. **Portal code** -- Short-lived, randomly generated (`number-word-word` format, ~20 bits of entropy). SPAKE2 prevents an eavesdropper from brute-forcing the code offline.
3. **End-to-end encryption** -- The relay server never sees message contents. All traffic is encrypted with NaCl SecretBox.

The portal is intentionally unrestricted once connected -- it can run any Python code, just like `plain shell`. The access control question is "can you start the remote process?" If you can, you already have full access anyway.

`--writable` controls database write access only, not general code execution.

## Platform compatibility

Portal works anywhere you can run a process with outbound internet access:

| Platform      | How to start the remote side                        |
| ------------- | --------------------------------------------------- |
| Heroku        | `heroku run plain portal start`                     |
| Fly.io        | `fly ssh console -C "plain portal start"`           |
| Kubernetes    | `kubectl exec -it deploy/app -- plain portal start` |
| Docker        | `docker exec -it container plain portal start`      |
| Any VM/server | `ssh myserver plain portal start`                   |

On the local side, run `plain portal connect <code>` in your normal terminal. No special setup needed.

## Relay server

The relay server is hosted at `portal.plainframework.com`. It runs on Cloudflare Workers with Durable Objects.

The relay is minimal:

- Each portal session is one Durable Object holding two WebSocket connections.
- The first connection arrives and waits. The second connection with the same channel ID arrives and they are paired.
- The relay forwards encrypted bytes between the two connections.
- When either side disconnects, the session is cleaned up.

The relay never sees plaintext. It has no knowledge of what commands are being run or what files are being transferred.

The relay host can be overridden with the `PLAIN_PORTAL_RELAY_HOST` environment variable.

## Activity log

The remote side logs every command to its terminal as it arrives. The person who started the portal session sees the full activity in real time:

```
Portal code: 7-crossword-pineapple
Session mode: read-only
Waiting for connection...

[14:32:01] Connected from remote client.
[14:32:05] exec: User.query.count()
           -> 4827
[14:32:12] exec: User.query.filter(active=False).values('email')[:5]
           -> [{'email': 'a@b.com'}, ...]
[14:33:01] pull: /tmp/export.csv
           sending export.csv (12400 bytes, 1 chunks)
[14:35:44] push: /tmp/fix.py (1 chunks)
           received 892 bytes
[14:50:01] Client disconnected.
```

This is important for the **support use case**: a customer running a self-hosted app can start a portal and share the code with the developer. The developer connects and debugs, but the customer watches the full session on their terminal. They see every command executed and every file transferred, and can Ctrl-C to kill the session at any time.

The customer does not need to grant SSH access, open firewall ports, or share credentials. They run `plain portal start`, share the code, and supervise.

### Idle timeout

The remote side auto-disconnects after 30 minutes of inactivity (no commands received). A warning is printed before disconnecting. The timeout is configurable:

```console
$ plain portal start --timeout 60   # 60 minutes
$ plain portal start --timeout 0    # no timeout
```

## Installation

Install from [PyPI](https://pypi.org/project/plain.portal/):

```bash
uv add plain.portal
```

No additional configuration is needed. The `plain portal` CLI commands are available immediately after installation.
