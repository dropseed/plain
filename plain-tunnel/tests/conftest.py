from __future__ import annotations

from plain.tunnel.client import TunnelClient


def make_client(*, subdomain="myapp", tunnel_host="plaintunnel.com"):
    return TunnelClient(
        destination_url="http://localhost:8000",
        subdomain=subdomain,
        tunnel_host=tunnel_host,
        log_level="WARNING",
    )
