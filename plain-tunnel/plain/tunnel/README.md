# plain.tunnel

**Connect to your local development server remotely.**

- [Overview](#overview)
- [Usage with plain.dev](#usage-with-plaindev)
- [CLI Usage](#cli-usage)
- [Configuration](#configuration)
    - [Environment Variables](#environment-variables)
    - [ALLOWED_HOSTS](#allowed_hosts)
- [Installation](#installation)

## Overview

The Plain Tunnel is a hosted service, like [ngrok](https://ngrok.com/) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/), that is specifically designed to work with Plain and provide the minimum set of features you need to get your local development server connected to the internet. It will provision a subdomain of plaintunnel.com for you, and forward traffic to your local development server.

This is especially useful for testing webhooks, doing mobile styling on a real device, or temporarily sharing your local development URL with someone.

Basic usage:

```console
plain tunnel https://app.localhost:8443
```

This will create a tunnel from a randomly generated subdomain to your local server. You can also specify a custom subdomain:

```console
plain tunnel https://app.localhost:8443 --subdomain myappname
```

## Usage with plain.dev

The simplest way to use `plain.tunnel` is to integrate it with your `plain.dev` configuration.

Add it to your `plain.dev` configuration in `pyproject.toml`:

```toml
[tool.plain.dev.run]
tunnel = {cmd = "plain tunnel $PLAIN_DEV_URL --subdomain myappname --quiet"}
```

To show a tunnel URL (whether you are using `plain.tunnel` or not), you can add `PLAIN_DEV_TUNNEL_URL` to your local `.env` file:

```bash
PLAIN_DEV_TUNNEL_URL=https://myappname.plaintunnel.com
```

![](https://assets.plainframework.com/docs/plain-dev-tunnel.png)

## CLI Usage

The [`cli`](./cli.py#cli) command accepts the following options:

- `destination`: The URL of your local development server (required)
- `--subdomain`: Custom subdomain to use (optional, auto-generated if not provided)
- `--debug`: Enable debug logging
- `--quiet`: Only log warnings and errors

Examples:

```console
# Basic usage with auto-generated subdomain
plain tunnel https://app.localhost:8443

# With custom subdomain
plain tunnel https://app.localhost:8443 --subdomain myapp

# With debug logging
plain tunnel https://app.localhost:8443 --debug

# One-off usage without installation
uvx plain-tunnel https://app.localhost:8443
```

## Configuration

### Environment Variables

The tunnel can be configured using environment variables:

- `PLAIN_TUNNEL_SUBDOMAIN`: Default subdomain to use
- `PLAIN_TUNNEL_HOST`: Tunnel host (defaults to plaintunnel.com)

## Installation

Install the `plain.tunnel` package from [PyPI](https://pypi.org/project/plain.tunnel/):

```bash
uv add plain.tunnel --dev
```
