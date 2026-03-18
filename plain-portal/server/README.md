# Portal Relay Server

Cloudflare Worker + Durable Objects relay for `plain portal`.

Pairs two WebSocket connections by a shared code and forwards encrypted
messages between them. The relay never sees plaintext.

## Local development

Terminal 1 (Worker):

```bash
cd plain-portal/server
npm install
npm run dev  # Runs on http://localhost:8787
```

Terminal 2 (Remote side):

```bash
PLAIN_PORTAL_RELAY_HOST=localhost:8787 uv run plain portal start
```

Terminal 3 (Local side):

```bash
PLAIN_PORTAL_RELAY_HOST=localhost:8787 uv run plain portal connect <code>
```

## Deploy

```bash
npm run deploy
```
