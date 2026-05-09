import click

import plain.runtime


@click.group()
def settings() -> None:
    """View and inspect settings"""
    pass


@settings.command()
@click.argument("setting_name")
def get(setting_name: str) -> None:
    """Get the value of a specific setting"""
    try:
        value = getattr(plain.runtime.settings, setting_name)
        click.echo(value)
    except AttributeError:
        click.secho(f'Setting "{setting_name}" not found', fg="red")


@settings.command(name="list")
def list_settings() -> None:
    """List all settings with their sources"""
    if not (items := plain.runtime.settings.get_settings()):
        click.echo("No settings configured.")
        return

    # Calculate column widths
    max_name = max(len(name) for name, _ in items)
    max_source = max(len(defn.env_var_name or defn.source) for _, defn in items)

    # Print header
    header = (
        click.style(f"{'Setting':<{max_name}}", bold=True)
        + "  "
        + click.style(f"{'Source':<{max_source}}", bold=True)
        + "  "
        + click.style("Value", bold=True)
    )
    click.echo(header)
    click.secho("-" * (max_name + max_source + 10), dim=True)

    # Print each setting
    for name, defn in items:
        source_info = defn.env_var_name or defn.source
        value = defn.display_value()

        # Style based on source
        if defn.source == "env":
            source_styled = click.style(f"{source_info:<{max_source}}", fg="green")
        elif defn.source == "explicit":
            source_styled = click.style(f"{source_info:<{max_source}}", fg="cyan")
        else:
            source_styled = click.style(f"{source_info:<{max_source}}", dim=True)

        # Style secret values
        if defn.is_secret:
            value_styled = click.style(value, dim=True)
        else:
            value_styled = value

        click.echo(f"{name:<{max_name}}  {source_styled}  {value_styled}")
