# Portal Relay Server (Cloudflare Worker)

## Local Development

Test changes to the relay without deploying to production.

**Terminal 1** — Start the Cloudflare Worker locally:

```
cd plain-portal/server
npm run dev
```

This starts `wrangler dev` on `http://localhost:8787` with `LOCALHOST_DEV=true`.

**Terminal 2** — Start the remote side:

```
PLAIN_PORTAL_RELAY_HOST=localhost:8787 uv run plain portal start
```

**Terminal 3** — Connect the local side:

```
PLAIN_PORTAL_RELAY_HOST=localhost:8787 uv run plain portal connect <code>
```

Then use `plain portal exec`, `pull`, `push` as normal.

## Deploying

```
cd plain-portal/server
npm run deploy
```

This deploys to `portal.plainframework.com` via Cloudflare. Bumping `MIN_PROTOCOL_VERSION` in `worker.js` will reject older clients — they'll see a message telling them to upgrade.
