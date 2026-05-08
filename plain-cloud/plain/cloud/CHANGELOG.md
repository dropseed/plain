# plain-cloud changelog

## [0.4.1](https://github.com/dropseed/plain/releases/plain-cloud@0.4.1) (2026-05-08)

### What's changed

- **`Client` mounts `/api` in `base_url`** so callers and the built-in commands target paths like `/me/`, `/apps/`, etc. directly — no need to keep `/api/` in every path string. ([08ba073fa5](https://github.com/dropseed/plain/commit/08ba073fa5))
- **`plain-cloud api <path>` accepts paths with or without the `/api/` prefix.** A redundant leading `/api/` is stripped before the request, so paths copied from `plain-cloud openapi` (which lists them without the mount prefix) work alongside the older prefixed form. ([08ba073fa5](https://github.com/dropseed/plain/commit/08ba073fa5))
- README and `api --help` examples updated to the prefix-less form.

### Upgrade instructions

- No changes required. Existing `/api/...` paths still work; new code can drop the prefix.

## [0.4.0](https://github.com/dropseed/plain/releases/plain-cloud@0.4.0) (2026-05-07)

First release of `plain-cloud` as a standalone command-line tool for managing your Plain Cloud account.

> **Note:** Earlier releases under the `plain.cloud` name on PyPI (0.1.0–0.3.3) shipped an OTLP observability exporter, which has moved to [`plain-connect`](https://pypi.org/project/plain-connect/). Those releases have been yanked. This 0.4.0 release is a different package with a different purpose.

### What's changed

- Initial CLI with `login`, `logout`, `whoami`, `apps list`, `api`, `open`, `openapi`, and `config` commands ([8847a1c](https://github.com/dropseed/plain/commit/8847a1cadde3))
- API tokens are stored in the OS keyring (Keychain / Credential Manager / Secret Service); the active api_url lives at `~/.plain/cloud/config.toml`
- `plain-cloud api <path>` mirrors `gh api` ergonomics: `-X` for method, `-H` for headers, `-f`/`-F` for fields, `--input` for raw bodies
- `plain-cloud openapi` fetches the API schema (no token required) — useful for piping into `jq` or feeding to an agent ([3b0a215](https://github.com/dropseed/plain/commit/3b0a215f8261))
- `PLAIN_CLOUD_TOKEN` and `PLAIN_CLOUD_API_URL` env vars work everywhere as overrides — useful for CI or headless boxes without a keyring backend ([d93f1e4](https://github.com/dropseed/plain/commit/d93f1e4ddcc6))

### Upgrade instructions

- If you were using the old `plain.cloud` OTLP exporter, install [`plain-connect`](https://pypi.org/project/plain-connect/) instead.
- New users: `uv tool install plain-cloud`, then `plain-cloud login`.
