---
packages:
  - plain.cli
related:
  - models-read-only-transactions
---

# Wormhole: Remote Python shell via encrypted tunnel

A way to open a Python shell on a remote machine (production dyno, container, VM) and send commands to it from your local machine — through an encrypted, ephemeral tunnel that requires only outbound connections on both sides.

## Why

Developers (and AI agents like Claude Code) need to explore production data, debug issues, and run one-off queries. Current options are bad:

- **`heroku run` per command** — 10-30s cold start, no state between commands
- **SSH/port forwarding** — platform-specific, different on every provider
- **HTTP endpoint on web process** — adds public attack surface to production
- **Direct DB connection** — loses access to app context (cache, env, services); code version mismatch risk

The wormhole approach: both sides make outbound WebSocket connections to a relay server, find each other via a short code, establish an E2E encrypted channel, and communicate through it. The remote side runs a Python REPL with the full app loaded.

## How it works

```
Production (heroku run, fly ssh, kubectl exec, etc.)     Local machine
┌──────────────────────┐                                  ┌──────────────────┐
│ plain wormhole       │───── outbound WSS ────▶          │                  │
│                      │                       ┌────────┐ │ plain wormhole   │
│ Python REPL with     │◀═══ encrypted msgs ══▶│ Relay  │◀│ 7-crossword-     │
│ app loaded, DB       │                       │ Server │ │ pineapple        │
│ connected            │                       └────────┘ │                  │
└──────────────────────┘                                  └──────────────────┘
```

1. Remote side runs `plain wormhole` — connects to relay, prints a short code (e.g. `7-crossword-pineapple`)
2. Local side runs `plain wormhole 7-crossword-pineapple` — connects to relay with the same code
3. SPAKE2 key exchange through the relay — both sides derive a shared secret from the human-readable code
4. All subsequent messages encrypted with nacl secretbox — relay never sees plaintext
5. Local side sends Python expressions, remote side executes them and returns `repr()` output
6. Session stays alive until either side disconnects

## CLI usage

```bash
# On production (via whatever mechanism the platform provides)
heroku run plain wormhole
fly ssh console -C "plain wormhole"
kubectl exec -it deploy/myapp -- plain wormhole

# Output:
# Wormhole code: 7-crossword-pineapple
# Waiting for connection...

# Locally (or Claude Code runs this)
plain wormhole 7-crossword-pineapple

# Now send commands
plain wormhole exec "User.objects.count()"
# → 4827

plain wormhole exec "User.objects.filter(active=False).values('email')[:5]"
# → [{'email': 'a@b.com'}, {'email': 'b@c.com'}, ...]
```

## Read-only by default

The wormhole session uses a read-only database transaction by default (Postgres `SET TRANSACTION READ ONLY`). Any write attempt raises a database error.

```bash
# Read-only (default)
plain wormhole

# Writable (explicit opt-in + confirmation prompt)
plain wormhole --writable
# "⚠ This session allows writes to the production database. Continue? [y/N]"
```

Uses the same `connection.read_only` mechanism from psycopg3 proposed in `models-read-only-transactions`.

## Output format

Default output matches Python REPL behavior — `repr()` of the result, tracebacks on errors. No magic.

A flag or command for JSON output when structured data is needed:

```bash
plain wormhole exec --json "User.objects.filter(active=False).values('email')[:5]"
```

## Relay server

Hosted at `wormhole.plainframework.com` on Cloudflare Workers + Durable Objects.

The relay is minimal:

- Each wormhole session = one Durable Object holding two WebSocket connections
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

## Stateful REPL

The remote side maintains a persistent Python namespace across commands. State carries over:

```bash
plain wormhole exec "qs = User.objects.filter(active=False)"
plain wormhole exec "qs.count()"
# → 312
plain wormhole exec "qs.first().date_joined"
# → datetime.datetime(2024, 3, 15, ...)
```

## Platform compatibility

Works anywhere you can run a process — the only requirement is outbound internet access:

| Platform      | How to start the remote side                    |
| ------------- | ----------------------------------------------- |
| Heroku        | `heroku run plain wormhole`                     |
| Fly.io        | `fly ssh console -C "plain wormhole"`           |
| Kubernetes    | `kubectl exec -it deploy/app -- plain wormhole` |
| Any VM/server | `ssh myserver plain wormhole`                   |
| Docker        | `docker exec -it container plain wormhole`      |

## Open questions

- Code format: `number-word-word` like magic-wormhole? How many words for sufficient entropy vs. usability?
- Brute-force protection: rate limiting on the relay for code guessing?
- Timeout: auto-disconnect after N minutes of inactivity?
- Truncation: cap output size for huge querysets? Or leave that to the user (`.[:10]`)?
