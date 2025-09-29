import click


def print_event(msg: str, newline: bool = True) -> None:
    arrow = click.style("-->", fg=214, bold=True)
    message = str(msg)
    if not newline:
        message += " "
    click.secho(f"{arrow} {message}", nl=newline)
