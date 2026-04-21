# MCP Conformance Testing

Runs the [MCP Conformance Test Framework](https://github.com/modelcontextprotocol/conformance) against a live plain-mcp server as part of `./scripts/test plain-mcp`.

## Layout

- `app/settings.py`, `app/urls.py` — a minimal Plain server that mounts an `MCP` view on `/mcp/`
- `app/mcp.py` — the `ConformanceMCP` subclass and the tools the conformance suite expects (`test_simple_text`, `test_error_handling`)
- `run` — starts the Plain server on `127.0.0.1:18765`, runs the conformance CLI against it, then shuts the server down
- `expected-failures.yml` — baseline of scenarios that plain-mcp does not yet pass

## How it runs

`scripts/test --server` invokes `tests/conformance/run` as part of the server-flag-gated suite (the conformance run spins up a live server and depends on Node, so it's not included in the default `scripts/test` pass). The runner:

1. Starts `plain server` with `app.settings` in a background process
2. Waits for `ping` to succeed
3. Invokes `npx --yes @modelcontextprotocol/conformance server --url … --expected-failures …`
4. Kills the server regardless of the outcome
5. Exits with the conformance CLI's exit code

If `npx` isn't on `PATH` the runner errors out — install Node.js before running this suite.

## Running it directly

```bash
plain-mcp/tests/conformance/run
```

Override the port with `MCP_CONFORMANCE_PORT=<port>`.

## Updating the baseline

The conformance CLI has four exit-code outcomes when `--expected-failures` is set:

| Run result | In baseline | Exit                                 |
| ---------- | ----------- | ------------------------------------ |
| Fails      | Yes         | 0 — expected failure                 |
| Fails      | No          | 1 — unexpected regression            |
| Passes     | Yes         | 1 — stale baseline, remove the entry |
| Passes     | No          | 0 — normal pass                      |

So when you ship a new MCP feature (e.g. prompts or resources), the runner will fail with "stale baseline" until you remove the now-passing scenarios from `expected-failures.yml`. That forces the baseline to track reality.
