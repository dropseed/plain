# Development

## Dev Server

Run `uv run plain dev` to start the development server with auto-reload and HTTPS.

The server URL will be displayed (typically `https://<project>.localhost:8443`).

View logs: `uv run plain dev logs`

## Tunnel URL

If `plain dev logs` shows a `Tunnel running at https://<subdomain>.plaintunnel.com`
line, that tunnel URL is the canonical app URL — use it for browser navigation,
screenshots, and shared links. Use the localhost `Server running at ...` URL only
when there's no tunnel, or for local CLI checks (`curl`, `plain request`).
