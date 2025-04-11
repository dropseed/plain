# plain.tunnel

**Connect to your local development server remotely.**

The Plain Tunnel is a hosted service, like [ngrok](https://ngrok.com/) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/), that is specifically designed to work with Plain and provide the minimum set of features you need to get your local development server connected to the internet. It will provision a subdomain of plaintunnel.com for you, and forward traffic to your local development server.

This is especially useful for testing webhooks, doing mobile styling on a real device, or temporarily sharing your local development URL with someone.

_Note: In the future this will likely require a small subscription to use custom subdomains (vs randomly generated ones)._

## Usage

The simplest way to use `plain.tunnel` is to install it from PyPI (`uv add plain.tunnel --dev`), then add it to your `plain.dev` configuration.

```toml
[tool.plain.dev.run]
tunnel = {cmd = "plain tunnel $PLAIN_DEV_URL --subdomain myappname --quiet"}
```

To show a tunnel URL (whether you are using `plain.tunnel` or not), you can add `PLAIN_DEV_TUNNEL_URL` to your local `.env` file.

```bash
PLAIN_DEV_TUNNEL_URL=https://myappname.plaintunnel.com
```

![](https://assets.plainframework.com/docs/plain-dev-tunnel.png)

Depending on your setup, you may need to add your tunnel to the `settings.ALLOWED_HOSTS`, which can be done in `settings.py` or in your dev `.env`.

```bash
PLAIN_ALLOWED_HOSTS='["*"]'
```

## CLI

To use `plain.tunnel` manually, you can use the `plain tunnel` command (or even use it as a one-off with something like `uvx plain-tunnel`).

```console
plain tunnel https://app.localhost:8443
```
