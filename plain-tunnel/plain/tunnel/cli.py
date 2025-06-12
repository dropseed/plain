import getpass
import random
import string

import click

from plain.cli import register_cli

from .client import TunnelClient


@register_cli("tunnel")
@click.command()
@click.argument("destination")
@click.option(
    "--subdomain",
    help="The subdomain to use for the tunnel.",
    envvar="PLAIN_TUNNEL_SUBDOMAIN",
)
@click.option(
    "--tunnel-host", envvar="PLAIN_TUNNEL_HOST", hidden=True, default="plaintunnel.com"
)
@click.option("--debug", "log_level", flag_value="DEBUG", help="Enable debug logging.")
@click.option(
    "--quiet", "log_level", flag_value="WARNING", help="Only log warnings and errors."
)
def cli(destination, subdomain, tunnel_host, log_level):
    if not destination.startswith("http://") and not destination.startswith("https://"):
        destination = f"https://{destination}"

    # Strip trailing slashes from the destination URL (maybe even enforce no path at all?)
    destination = destination.rstrip("/")

    if not log_level:
        log_level = "INFO"

    if not subdomain:
        # Generate a subdomain using the system username + 7 random characters
        random_chars = "".join(random.choices(string.ascii_lowercase, k=7))
        subdomain = f"{getpass.getuser()}-{random_chars}"

    tunnel = TunnelClient(
        destination_url=destination,
        subdomain=subdomain,
        tunnel_host=tunnel_host,
        log_level=log_level,
    )
    click.secho(f"Tunneling {tunnel.tunnel_http_url} -> {destination}", bold=True)
    tunnel.run()
