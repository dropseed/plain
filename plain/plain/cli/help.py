import click
from click.core import Group


@click.command("help")
@click.pass_context
def help_cmd(ctx):
    """Show help for all commands and subcommands."""

    root = ctx.parent.command
    info_name = ctx.parent.info_name or "plain"

    def print_help(cmd, prog, parent=None):
        sub_ctx = click.Context(cmd, info_name=prog, parent=parent)

        title = sub_ctx.command_path
        click.secho(title, fg="green", bold=True)
        click.secho("-" * len(title), fg="green")
        click.echo(sub_ctx.get_help())

        if isinstance(cmd, Group):
            for name in cmd.list_commands(sub_ctx):
                click.echo()
                sub_cmd = cmd.get_command(sub_ctx, name)
                print_help(sub_cmd, name, sub_ctx)

    print_help(root, info_name)
