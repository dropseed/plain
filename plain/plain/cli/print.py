import click


def print_event(msg: str, newline: bool = True) -> None:
    arrow = click.style("-->", fg=214, bold=True, dim=True)
    message = click.style(msg, dim=True)
    if not newline:
        message += " "
    click.echo(f"{arrow} {message}", nl=newline)
