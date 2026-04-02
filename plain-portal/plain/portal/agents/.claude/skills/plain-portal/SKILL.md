---
name: plain-portal
description: Open a remote Python shell on a production machine via encrypted tunnel. Use when you need to inspect production data, debug issues, run queries, or transfer files.
disable-model-invocation: true
---

# Remote Portal Session

Open an encrypted tunnel to a remote machine and run Python code on it.

## 1. Start the remote side and connect

The remote side must be running first. Either start it yourself (if you have access to the platform CLI) or ask the user to start it:

| Platform   | Command                                             |
| ---------- | --------------------------------------------------- |
| Heroku     | `heroku run plain portal start`                     |
| Fly.io     | `fly ssh console -C "plain portal start"`           |
| Kubernetes | `kubectl exec -it deploy/app -- plain portal start` |
| Docker     | `docker exec -it container plain portal start`      |
| SSH        | `ssh server plain portal start`                     |

**Both `start` and `connect` are long-running foreground processes.** If you run `start` yourself, use `run_in_background` so you don't block. Once it prints a portal code (e.g. `7-crossword-pineapple`), read the code from the output. If the user ran it, ask them for the code.

Then connect (also use `run_in_background`):

```
uv run plain portal connect <code>
```

## 2. Run commands

Execute Python code on the remote machine:

```
uv run plain portal exec "<code>"
```

Output streams line by line in real time. The last expression's value is returned (like a REPL).

For long-running commands, increase the timeout (default 120s):

```
uv run plain portal exec --timeout 300 "<code>"
```

For machine-readable output:

```
uv run plain portal exec --json "<expression>"
```

### File transfer

```
uv run plain portal pull <remote_path> <local_path>
uv run plain portal push <local_path> <remote_path>
```

Push is restricted to `/tmp/` on the remote machine.

## 3. Disconnect

Kill the `connect` process to end the session. This also frees the remote process.

## Important

- Sessions are **read-only** by default. Database writes will fail unless the remote was started with `--writable --yes`.
- Each `exec` gets a **fresh namespace**. Variables don't carry between commands. Put setup and queries in one code block if they depend on each other.
- Use `plain portal exec` for quick queries. For heavy data export, write to `/tmp/` on the remote and `pull` the file.
- If the session drops, the remote side must be restarted and a new code used to reconnect.
