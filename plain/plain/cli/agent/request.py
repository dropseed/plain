import json

import click

from plain.runtime import settings
from plain.test import Client


@click.command()
@click.argument("path")
@click.option(
    "--method",
    default="GET",
    help="HTTP method (GET, POST, PUT, PATCH, DELETE, etc.)",
)
@click.option(
    "--data",
    help="Request data (JSON string for POST/PUT/PATCH)",
)
@click.option(
    "--user",
    "user_id",
    help="User ID to authenticate as (skips normal authentication)",
)
@click.option(
    "--follow/--no-follow",
    default=True,
    help="Follow redirects (default: True)",
)
@click.option(
    "--content-type",
    help="Content-Type header for request data",
)
@click.option(
    "--header",
    "headers",
    multiple=True,
    help="Additional headers (format: 'Name: Value')",
)
def request(path, method, data, user_id, follow, content_type, headers):
    """Make an HTTP request using the test client against the development database."""

    try:
        # Only allow in DEBUG mode for security
        if not settings.DEBUG:
            click.secho("This command only works when DEBUG=True", fg="red", err=True)
            return

        # Temporarily add testserver to ALLOWED_HOSTS so the test client can make requests
        original_allowed_hosts = settings.ALLOWED_HOSTS
        settings.ALLOWED_HOSTS = ["*"]

        try:
            # Create test client
            client = Client()

            # If user_id provided, force login
            if user_id:
                try:
                    # Get the User model using plain.auth utility
                    from plain.auth import get_user_model

                    User = get_user_model()

                    # Get the user
                    try:
                        user = User.query.get(id=user_id)
                        client.force_login(user)
                        click.secho(
                            f"Authenticated as user {user_id}", fg="green", dim=True
                        )
                    except User.DoesNotExist:
                        click.secho(f"User {user_id} not found", fg="red", err=True)
                        return

                except Exception as e:
                    click.secho(f"Authentication error: {e}", fg="red", err=True)
                    return

            # Parse additional headers
            header_dict = {}
            for header in headers:
                if ":" in header:
                    key, value = header.split(":", 1)
                    header_dict[key.strip()] = value.strip()

            # Prepare request data
            if data and content_type and "json" in content_type.lower():
                try:
                    # Validate JSON
                    json.loads(data)
                except json.JSONDecodeError as e:
                    click.secho(f"Invalid JSON data: {e}", fg="red", err=True)
                    return

            # Make the request
            method = method.upper()
            kwargs = {
                "path": path,
                "follow": follow,
                "headers": header_dict or None,
            }

            if method in ("POST", "PUT", "PATCH") and data:
                kwargs["data"] = data
                if content_type:
                    kwargs["content_type"] = content_type

            # Call the appropriate client method
            if method == "GET":
                response = client.get(**kwargs)
            elif method == "POST":
                response = client.post(**kwargs)
            elif method == "PUT":
                response = client.put(**kwargs)
            elif method == "PATCH":
                response = client.patch(**kwargs)
            elif method == "DELETE":
                response = client.delete(**kwargs)
            elif method == "HEAD":
                response = client.head(**kwargs)
            elif method == "OPTIONS":
                response = client.options(**kwargs)
            elif method == "TRACE":
                response = client.trace(**kwargs)
            else:
                click.secho(f"Unsupported HTTP method: {method}", fg="red", err=True)
                return

            # Display response information
            click.secho(
                f"HTTP {response.status_code}",
                fg="green" if response.status_code < 400 else "red",
                bold=True,
            )

            # Show additional response info first
            if hasattr(response, "user"):
                click.secho(f"Authenticated user: {response.user}", fg="blue", dim=True)

            if hasattr(response, "resolver_match") and response.resolver_match:
                match = response.resolver_match
                url_name = match.namespaced_url_name or match.url_name or "unnamed"
                click.secho(f"URL pattern matched: {url_name}", fg="blue", dim=True)

            # Show headers
            if response.headers:
                click.secho("Response Headers:", fg="yellow", bold=True)
                for key, value in response.headers.items():
                    click.echo(f"  {key}: {value}")
                click.echo()

            # Show response content last
            if response.content:
                content_type = response.headers.get("Content-Type", "")

                if "json" in content_type.lower():
                    try:
                        json_data = response.json()
                        click.secho("Response Body (JSON):", fg="yellow", bold=True)
                        click.echo(json.dumps(json_data, indent=2))
                    except Exception:
                        click.secho("Response Body:", fg="yellow", bold=True)
                        click.echo(response.content.decode("utf-8", errors="replace"))
                elif "html" in content_type.lower():
                    click.secho("Response Body (HTML):", fg="yellow", bold=True)
                    content = response.content.decode("utf-8", errors="replace")
                    click.echo(content)
                else:
                    click.secho("Response Body:", fg="yellow", bold=True)
                    content = response.content.decode("utf-8", errors="replace")
                    click.echo(content)
            else:
                click.secho("(No response body)", fg="yellow", dim=True)

        finally:
            # Restore original ALLOWED_HOSTS
            settings.ALLOWED_HOSTS = original_allowed_hosts

    except Exception as e:
        click.secho(f"Request failed: {e}", fg="red", err=True)
