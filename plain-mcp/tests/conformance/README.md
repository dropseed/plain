# MCP Conformance Testing

Runs the [MCP Conformance Test Framework](https://github.com/modelcontextprotocol/conformance) against a live plain-mcp server as part of `./scripts/test plain-mcp`.

## Layout

- `app/settings.py`, `app/urls.py` — a minimal Plain server that mounts an `MCP` view on `/mcp`
- `app/mcp.py` — the `ConformanceMCP` subclass and the tools the conformance suite expects (`test_simple_text`, `test_error_handling`)
- `run` — starts the Plain server on `127.0.0.1:18765`, runs the conformance CLI against it (two passes, see below), then shuts the server down
- `expected-failures.yml` — baseline of `2026-07-28` checks that plain-mcp does not yet pass
- `expected-failures-classic.yml` — baseline for the classic pass (`--spec-version 2025-11-25`), which grades the compatibility branch (`handle_classic_message`) against the handshake-era protocol; its entries are the optional features unimplemented on either path

## How it runs

`scripts/test --server` invokes `tests/conformance/run` as part of the server-flag-gated suite (the conformance run spins up a live server and depends on Node, so it's not included in the default `scripts/test` pass). The runner:

1. Starts `plain server` with `app.settings` in a background process
2. Waits for the endpoint to respond at all (any status — the CLI negotiates the protocol itself)
3. Invokes `npx --yes @modelcontextprotocol/conformance@<pinned> server --url … --spec-version 2026-07-28 --expected-failures …`
4. Repeats at `--spec-version 2025-11-25` with `expected-failures-classic.yml`, so the classic compatibility branch has its own machine-checked contract
5. Kills the server regardless of the outcome
6. Exits non-zero if either pass regresses (or a baseline goes stale)

If `npx` isn't on `PATH` the runner errors out — install Node.js before running this suite.

## Pinned CLI version

`2026-07-28` scenarios only exist in the CLI's `0.2` alphas — its `latest`
release still tops out at `2025-11-25`. The runner pins an exact alpha rather
than tracking the moving `alpha` tag, so a run is reproducible; bump
`CONFORMANCE_PACKAGE` in `run` when `0.2.0` ships stable.

## Running it directly

```bash
plain-mcp/tests/conformance/run
```

Override the port with `MCP_CONFORMANCE_PORT=<port>`.

## Interactive testing with the MCP Inspector

The conformance suite proves plain-mcp obeys the spec. To drive a real server's
_tools_ — with no Claude/Cursor account — use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
via `./scripts/inspect-mcp`, which boots the **example app**'s `NotesMCP` server
on a local HTTP port and points the Inspector at it.

> MCP Inspector v0.22.0 is a legacy-era client: it opens with an `initialize`
> handshake, which `2026-07-28` removed — it connects through the classic
> compatibility branch, so what it exercises is that branch, not the modern
> `_meta`/header envelope the conformance suite covers.

```bash
./scripts/inspect-mcp                            # interactive web UI
./scripts/inspect-mcp --cli --method tools/list  # scripted, no browser
./scripts/inspect-mcp --cli --method tools/call --tool-name WhoAmI
```

`tools/list` works without a database; tool calls that hit the DB need Postgres
(`./scripts/start-postgres`). Override the port with `INSPECT_MCP_PORT=<port>`.

The `--cli` path sends the bearer correctly with no extra step. In the **web UI**,
MCP Inspector v0.22.0 prefills the `Authorization` header but doesn't apply a
_restored_ value until it's edited — re-type the bearer (`local-dev-only`) in
Authentication → Custom Headers before clicking Connect, or the server returns
`401 Missing Authorization header`.

## Updating the baseline

The conformance CLI has four exit-code outcomes when `--expected-failures` is set:

| Run result | In baseline | Exit                                 |
| ---------- | ----------- | ------------------------------------ |
| Fails      | Yes         | 0 — expected failure                 |
| Fails      | No          | 1 — unexpected regression            |
| Passes     | Yes         | 1 — stale baseline, remove the entry |
| Passes     | No          | 0 — normal pass                      |

So when you ship a new MCP feature (e.g. completions or SEP-2322 mid-request input), the runner will fail with "stale baseline" until you remove the now-passing entries from `expected-failures.yml`. That forces the baseline to track reality.

There are two entry forms, and picking the right one decides how much a listed scenario can hide:

| Form                | Exempts                     | Goes stale when           | Use for                               |
| ------------------- | --------------------------- | ------------------------- | ------------------------------------- |
| `scenario`          | every check in the scenario | the whole scenario passes | a feature that isn't built at all     |
| `scenario:check-id` | that one check              | that check passes         | a scenario that already partly passes |

The CLI rejects mixing both forms for the same scenario. Today every baselined scenario is a feature we haven't built, so all entries are the bare wildcard form; reach for `scenario:check-id` the moment a scenario starts passing some of its checks, so the rest can't regress unnoticed.
