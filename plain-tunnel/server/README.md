# Tunnel Server (Cloudflare Worker)

## Local Development

Test changes to the tunnel protocol without deploying to production.

**Terminal 1** — Start the Cloudflare Worker locally:

```
cd plain-tunnel/server
npm run dev
```

This starts `wrangler dev` on `http://localhost:8787` with `LOCALHOST_DEV=true` (skips subdomain routing).

**Terminal 2** — Start the example app:

```
cd example
uv run plain dev
```

**Terminal 3** — Connect the tunnel client to the local worker:

```
cd example
PLAIN_TUNNEL_HOST=localhost:8787 uv run plain tunnel https://example.localhost:8443 --subdomain dev --debug
```

Then open `http://localhost:8787/` in your browser. All requests go through the local worker → tunnel client → example app.

To test SSE streaming, visit `http://localhost:8787/sse/`.

## Deploying

```
cd plain-tunnel/server
npm run deploy
```

This deploys to `plaintunnel.com` via Cloudflare. Bumping `MIN_PROTOCOL_VERSION` in `worker.js` will reject older clients — they'll see a message telling them to upgrade.
