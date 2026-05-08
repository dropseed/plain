# plain.cloud

**Command-line tool for Plain Cloud.**

- [Overview](#overview)
- [Commands](#commands)
- [Self-hosted / staging](#self-hosted--staging)
- [Headless / CI use](#headless--ci-use)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Mint a personal API token at `https://plainframework.com/dashboard/api-keys/`, then log in. The token is stored in your OS keyring (Keychain on macOS, Credential Manager on Windows, Secret Service on Linux); the api_url lives in plain text at `~/.plain/cloud/config.toml`.

```
plain-cloud login
plain-cloud whoami
plain-cloud apps list
```

## Commands

- `plain-cloud login` — paste a token, validate it, and save it to your OS keyring.
- `plain-cloud logout` — forget the saved token.
- `plain-cloud whoami` — show the user the current token belongs to.
- `plain-cloud apps list` — list apps you have access to across every team.
- `plain-cloud api <path>` — call any API path with the saved token. Modeled on `gh api`: `-X/--method` (default `GET`); `-H KEY:VALUE` for headers; `-f key=value` for string fields; `-F key=value` for typed fields (`true`/`false`/`null`/numbers become JSON literals, `@path` reads a string from disk); `--input FILE` (or `-` for stdin) to send a raw body; `--raw` to skip JSON pretty-printing. Fields go in the query string for `GET` and in the JSON body otherwise. Exit code is 0 for 2xx, 1 otherwise.

Pass paths exactly as listed in `plain-cloud openapi` — the `/api/` mount prefix is added for you (passing it explicitly also works).

```
plain-cloud api /me/
plain-cloud api /apps/ -F page=2
plain-cloud api /apps/foo/exceptions/abc123/resolve/ -X POST
plain-cloud api /apps/ -X POST --input body.json -H "X-Trace: 1"
```

- `plain-cloud openapi` — fetch the OpenAPI document. No token required (the schema is metadata). Pipe into `jq` or save with `> openapi.json` to feed to an agent.
- `plain-cloud open [path]` — open a Plain Cloud URL in your browser. Defaults to `/dashboard/`.
- `plain-cloud config` — show the active keyring backend and api_url.

## Self-hosted / staging

Pass `--api-url` at login to point at a non-production install:

```
plain-cloud login --api-url https://plain-cloud.example.com
```

## Headless / CI use

Skip `login` entirely and pass the token via env var. This works everywhere — useful for CI, Docker, and headless Linux boxes that don't ship a keyring backend, but also as a per-shell override on a machine that's already logged in.

```
PLAIN_CLOUD_TOKEN=...           # required
PLAIN_CLOUD_API_URL=...         # optional, defaults to https://plainframework.com
```

When `PLAIN_CLOUD_TOKEN` is set, it overrides anything stored in the keyring.

## FAQs

#### Where is my token stored?

In your OS keyring under the service name `plain-cloud`, keyed by the api_url. Run `plain-cloud config` to see which backend is active.

#### Can I have prod and staging tokens at the same time?

Tokens are keyed by api_url in the keyring, so multiple installations coexist. The `config.toml` tracks the most recent login; switch by running `plain-cloud login --api-url ...` again.

#### What if `login` says "no OS keyring backend available"?

You're on a system without a keyring (common on headless Linux). Use the `PLAIN_CLOUD_TOKEN` env var instead — see [Headless / CI use](#headless--ci-use).

## Installation

```
uv tool install plain-cloud
```
