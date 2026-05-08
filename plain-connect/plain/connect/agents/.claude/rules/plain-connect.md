# Plain Connect

`plain.connect` exports this app's traces, metrics, logs, and exceptions to Plain Cloud. To read that data back (when investigating production exceptions, slow endpoints, slow queries, recent deploys, etc.), use the separate `plain-cloud` CLI.

If `plain-cloud` isn't on PATH, prefix any command with `uvx` (e.g. `uvx plain-cloud apps list`) — it runs without installing and shares the OS keyring with an installed copy.

## Discovery first

API endpoints evolve — don't hardcode paths from memory. Discover the current surface before calling anything:

- `plain-cloud --help` — top-level commands
- `plain-cloud api --help` — flags for arbitrary API calls (modeled on `gh api`)
- `plain-cloud openapi | jq '.paths | keys'` — list every available endpoint
- `plain-cloud openapi | jq '.paths."<path>"'` — inspect a specific endpoint's params and response

## Calling the API

`plain-cloud api <path>` runs an authenticated request and prints the JSON response. Pass paths exactly as listed by `openapi` — use `apps list` first to get the slug, then drill in.

## Auth

First-time setup requires the user to run `plain-cloud login` (or `uvx plain-cloud login`) — it prompts for a token interactively and stores it in the OS keyring. If `plain-cloud whoami` fails or any call returns 401, ask the user to log in; don't try to set tokens or write credentials on their behalf.
