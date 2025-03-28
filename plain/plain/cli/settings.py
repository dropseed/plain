import click

import plain.runtime


@click.command()
@click.argument("setting_name")
def setting(setting_name):
    """Print the value of a setting at runtime"""
    try:
        setting = getattr(plain.runtime.settings, setting_name)
        click.echo(setting)
    except AttributeError:
        click.secho(f'Setting "{setting_name}" not found', fg="red")


# @plain_cli.command()
# @click.option("--filter", "-f", "name_filter", help="Filter settings by name")
# @click.option("--overridden", is_flag=True, help="Only show overridden settings")
# def settings(name_filter, overridden):
#     """Print Plain settings"""
#     table = Table(box=box.MINIMAL)
#     table.add_column("Setting")
#     table.add_column("Default value")
#     table.add_column("App value")
#     table.add_column("Type")
#     table.add_column("Module")

#     for setting in dir(settings):
#         if setting.isupper():
#             if name_filter and name_filter.upper() not in setting:
#                 continue

#             is_overridden = settings.is_overridden(setting)

#             if overridden and not is_overridden:
#                 continue

#             default_setting = settings._default_settings.get(setting)
#             if default_setting:
#                 default_value = default_setting.value
#                 annotation = default_setting.annotation
#                 module = default_setting.module
#             else:
#                 default_value = ""
#                 annotation = ""
#                 module = ""

#             table.add_row(
#                 setting,
#                 Pretty(default_value) if default_value else "",
#                 Pretty(getattr(settings, setting))
#                 if is_overridden
#                 else Text("<Default>", style="italic dim"),
#                 Pretty(annotation) if annotation else "",
#                 str(module.__name__) if module else "",
#             )

#     console = Console()
#     console.print(table)
