import json
import sys

import click
import requests

from plain.cli import register_cli
from plain.runtime import settings
from plain.utils.module_loading import import_string

from .openapi.generator import OpenAPISchemaGenerator


@register_cli("api")
@click.group()
def cli():
    """API commands."""
    pass


@cli.command()
@click.option("--validate", is_flag=True, help="Validate the OpenAPI schema.")
@click.option("--indent", default=2, help="Indentation level for JSON and YAML output.")
@click.option(
    "--format",
    default="json",
    help="Output format (json or yaml).",
    type=click.Choice(["json", "yaml"]),
)
def generate_openapi(validate, indent, format):
    if not settings.API_OPENAPI_ROUTER:
        click.secho("No OpenAPI URL router configured.", fg="red", err=True)
        sys.exit(1)

    url_router_class = import_string(settings.API_OPENAPI_ROUTER)

    schema = OpenAPISchemaGenerator(url_router_class)

    if format == "json":
        print(schema.as_json(indent=indent))
    elif format == "yaml":
        print(schema.as_yaml(indent=indent))

    if validate:
        click.secho("\nOpenAPI schema validation: ", err=True, nl=False)
        response = requests.post(
            "https://validator.swagger.io/validator/debug",
            headers={"Content-Type": "application/json"},
            json=schema.schema,
        )
        response.raise_for_status()
        failed = response.json().get(
            "schemaValidationMessages", []
        ) or response.json().get("messages", [])
        if failed:
            click.secho("Failed", fg="red", err=True)
            click.secho(
                json.dumps(response.json(), indent=2, sort_keys=True),
                fg="yellow",
                err=True,
            )
            sys.exit(1)
        else:
            click.secho("Success", fg="green", err=True)
