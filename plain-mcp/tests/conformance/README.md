# MCP Conformance Testing

Runs the [MCP Conformance Test Framework](https://github.com/modelcontextprotocol/conformance) against a live plain-mcp server as part of `./scripts/test plain-mcp`.

## Layout

- `app/settings.py`, `app/urls.py` — a minimal Plain server that mounts `MCPRouter` on `/mcp/`
- `app/mcp.py` — the tools and resources the conformance suite expects (`test_simple_text`, `test_error_handling`, `test://static-text`)
- `run` — starts the Plain server on `127.0.0.1:18765`, runs the conformance CLI against it, then shuts the server down
- `expected-failures.yml` — baseline of scenarios that plain-mcp does not yet pass

## How it runs

`scripts/test plain-mcp` invokes `tests/conformance/run` after the pytest suite. The runner:

1. Starts `plain server` with `app.settings` in a background process
2. Waits for `ping` to succeed
3. Invokes `npx --yes @modelcontextprotocol/conformance server --url … --expected-failures …`
4. Kills the server regardless of the outcome
5. Exits with the conformance CLI's exit code

If `npx` isn't on `PATH` the runner prints a skip notice and exits 0, so devs without Node can still run the rest of the suite.

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

So when you ship a new MCP feature (e.g. prompts), the runner will fail with "stale baseline" until you remove the now-passing scenarios from `expected-failures.yml`. That forces the baseline to track reality.

## Currently passing scenarios

- `server-initialize`
- `ping`
- `tools-list`
- `tools-call-simple-text`
- `tools-call-error`
- `resources-list`
- `resources-read-text`
- `dns-rebinding-protection`

Everything else is listed in `expected-failures.yml` with a short note about what feature it needs.
