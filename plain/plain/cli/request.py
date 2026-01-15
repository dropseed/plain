from __future__ import annotations

import json
from typing import Any

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
@click.option(
    "--no-headers",
    is_flag=True,
    help="Hide response headers from output",
)
@click.option(
    "--no-body",
    is_flag=True,
    help="Hide response body from output",
)
def request(
    path: str,
    method: str,
    data: str | None,
    user_id: str | None,
    follow: bool,
    content_type: str | None,
    headers: tuple[str, ...],
    no_headers: bool,
    no_body: bool,
) -> None:
    """Make HTTP requests against the dev database"""

    try:
        # Only allow in DEBUG mode for security
        if not settings.DEBUG:
            click.secho("This command only works when DEBUG=True", fg="red", err=True)
            return

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
        kwargs: dict[str, Any] = {
            "follow": follow,
        }
        if header_dict:
            kwargs["headers"] = header_dict

        if method in ("POST", "PUT", "PATCH") and data:
            kwargs["data"] = data
            if content_type:
                kwargs["content_type"] = content_type

        # Call the appropriate client method
        if method == "GET":
            response = client.get(path, **kwargs)
        elif method == "POST":
            response = client.post(path, **kwargs)
        elif method == "PUT":
            response = client.put(path, **kwargs)
        elif method == "PATCH":
            response = client.patch(path, **kwargs)
        elif method == "DELETE":
            response = client.delete(path, **kwargs)
        elif method == "HEAD":
            response = client.head(path, **kwargs)
        elif method == "OPTIONS":
            response = client.options(path, **kwargs)
        elif method == "TRACE":
            response = client.trace(path, **kwargs)
        else:
            click.secho(f"Unsupported HTTP method: {method}", fg="red", err=True)
            return

        # Display response information
        click.secho("Response:", fg="yellow", bold=True)

        # Status code
        click.echo(f"  Status: {response.status_code}")

        # Request ID
        click.echo(f"  Request ID: {response.wsgi_request.unique_id}")

        # User
        if response.user:
            click.echo(f"  Authenticated user: {response.user}")

        # URL pattern
        if response.resolver_match:
            match = response.resolver_match
            namespaced_url_name = getattr(match, "namespaced_url_name", None)
            url_name_attr = getattr(match, "url_name", None)
            url_name = namespaced_url_name or url_name_attr
            if url_name:
                click.echo(f"  URL pattern: {url_name}")

        click.echo()

        # Show headers
        if response.headers and not no_headers:
            click.secho("Response Headers:", fg="yellow", bold=True)
            for key, value in response.headers.items():
                click.echo(f"  {key}: {value}")
            click.echo()

        # Show response content last
        if response.content and not no_body:
            content_type = response.headers.get("Content-Type", "")

            if "json" in content_type.lower():
                try:
                    # The test client adds a json() method to the response
                    json_method = getattr(response, "json", None)
                    if json_method and callable(json_method):
                        json_data: Any = json_method()
                        click.secho("Response Body (JSON):", fg="yellow", bold=True)
                        click.echo(json.dumps(json_data, indent=2))
                    else:
                        click.secho("Response Body:", fg="yellow", bold=True)
                        click.echo(response.content.decode("utf-8", errors="replace"))
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
        elif not no_body:
            click.secho("(No response body)", fg="yellow", dim=True)

    except Exception as e:
        click.secho(f"Request failed: {e}", fg="red", err=True)
