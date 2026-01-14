# plain.tunnel

**Expose your local development server to the internet.**

- [Overview](#overview)
- [Integrating with plain.dev](#integrating-with-plaindev)
- [CLI options](#cli-options)
- [Environment variables](#environment-variables)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain Tunnel is a hosted tunneling service that gives your local development server a public URL. You can use it to test webhooks from third-party services, preview your site on a mobile device, or share your work with someone temporarily.

To create a tunnel, run:

```console
plain tunnel https://app.localhost:8443
```

This connects your local server to a randomly generated subdomain like `yourname-abc1234.plaintunnel.com`. The tunnel stays open until you stop it with Ctrl+C.

To use a consistent subdomain, pass the `--subdomain` option:

```console
plain tunnel https://app.localhost:8443 --subdomain myapp
```

Now your tunnel will always be available at `https://myapp.plaintunnel.com`.

## Integrating with plain.dev

You can run the tunnel automatically alongside your development server by adding it to your `pyproject.toml`:

```toml
[tool.plain.dev.run]
tunnel = {cmd = "plain tunnel $PLAIN_DEV_URL --subdomain myapp --quiet"}
```

The `$PLAIN_DEV_URL` variable is automatically set to your local server URL. The `--quiet` flag reduces log output so it does not clutter your terminal.

To display the tunnel URL in the `plain dev` header, add `PLAIN_DEV_TUNNEL_URL` to your `.env` file:

```bash
PLAIN_DEV_TUNNEL_URL=https://myapp.plaintunnel.com
```

![](https://assets.plainframework.com/docs/plain-dev-tunnel.png)

## CLI options

The [`cli`](./cli.py#cli) command accepts these options:

| Option        | Description                         |
| ------------- | ----------------------------------- |
| `destination` | URL of your local server (required) |
| `--subdomain` | Custom subdomain to use             |
| `--debug`     | Enable debug logging                |
| `--quiet`     | Only log warnings and errors        |

Examples:

```console
# With debug logging to troubleshoot connection issues
plain tunnel https://app.localhost:8443 --debug

# Run as a standalone tool without installing
uvx plain-tunnel https://app.localhost:8443
```

## Environment variables

You can configure the tunnel using environment variables instead of CLI options:

| Variable                 | Description                                 |
| ------------------------ | ------------------------------------------- |
| `PLAIN_TUNNEL_SUBDOMAIN` | Default subdomain to use                    |
| `PLAIN_TUNNEL_HOST`      | Tunnel host (defaults to `plaintunnel.com`) |

## FAQs

#### How does the tunnel work?

The tunnel establishes a WebSocket connection to the Plain Tunnel server. When a request arrives at your public URL, the server forwards it through the WebSocket to your local machine. The [`TunnelClient`](./client.py#TunnelClient) then makes the request to your local server and sends the response back.

#### What happens if the connection drops?

The tunnel automatically reconnects if the connection is lost. It will retry up to 5 times with a 2-second delay between attempts.

#### Can I use this without installing Plain?

Yes. You can run the tunnel as a standalone tool using `uvx`:

```console
uvx plain-tunnel https://localhost:8000
```

#### Do I need to configure ALLOWED_HOSTS?

If you are using Plain with a custom subdomain, you may need to add it to your `ALLOWED_HOSTS` setting:

```python
# app/settings.py
ALLOWED_HOSTS = [
    "localhost",
    "app.localhost",
    "myapp.plaintunnel.com",
]
```

## Installation

Install from [PyPI](https://pypi.org/project/plain.tunnel/):

```bash
uv add plain.tunnel --dev
```

Then run the tunnel:

```console
plain tunnel https://app.localhost:8443
```
