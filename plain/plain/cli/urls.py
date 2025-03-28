import sys

import click


@click.command()
@click.option("--flat", is_flag=True, help="List all URLs in a flat list")
def urls(flat):
    """Print all URL patterns under settings.URLS_ROUTER"""
    from plain.runtime import settings
    from plain.urls import URLResolver, get_resolver

    if not settings.URLS_ROUTER:
        click.secho("URLS_ROUTER is not set", fg="red")
        sys.exit(1)

    resolver = get_resolver(settings.URLS_ROUTER)
    if flat:

        def flat_list(patterns, prefix="", curr_ns=""):
            for pattern in patterns:
                full_pattern = f"{prefix}{pattern.pattern}"
                if isinstance(pattern, URLResolver):
                    # Update current namespace
                    new_ns = (
                        f"{curr_ns}:{pattern.namespace}"
                        if curr_ns and pattern.namespace
                        else (pattern.namespace or curr_ns)
                    )
                    yield from flat_list(
                        pattern.url_patterns, prefix=full_pattern, curr_ns=new_ns
                    )
                else:
                    if pattern.name:
                        if curr_ns:
                            styled_namespace = click.style(f"{curr_ns}:", fg="yellow")
                            styled_name = click.style(pattern.name, fg="blue")
                            full_name = f"{styled_namespace}{styled_name}"
                        else:
                            full_name = click.style(pattern.name, fg="blue")
                        name_part = f" [{full_name}]"
                    else:
                        name_part = ""
                    yield f"{click.style(full_pattern)}{name_part}"

        for p in flat_list(resolver.url_patterns):
            click.echo(p)
    else:

        def print_tree(patterns, prefix="", curr_ns=""):
            count = len(patterns)
            for idx, pattern in enumerate(patterns):
                is_last = idx == (count - 1)
                connector = "└── " if is_last else "├── "
                styled_connector = click.style(connector)
                styled_pattern = click.style(pattern.pattern)
                if isinstance(pattern, URLResolver):
                    if pattern.namespace:
                        new_ns = (
                            f"{curr_ns}:{pattern.namespace}"
                            if curr_ns
                            else pattern.namespace
                        )
                        styled_namespace = click.style(f"[{new_ns}]", fg="yellow")
                        click.echo(
                            f"{prefix}{styled_connector}{styled_pattern} {styled_namespace}"
                        )
                    else:
                        new_ns = curr_ns
                        click.echo(f"{prefix}{styled_connector}{styled_pattern}")
                    extension = "    " if is_last else "│   "
                    print_tree(pattern.url_patterns, prefix + extension, new_ns)
                else:
                    if pattern.name:
                        if curr_ns:
                            styled_namespace = click.style(f"{curr_ns}:", fg="yellow")
                            styled_name = click.style(pattern.name, fg="blue")
                            full_name = f"[{styled_namespace}{styled_name}]"
                        else:
                            full_name = click.style(f"[{pattern.name}]", fg="blue")
                        click.echo(
                            f"{prefix}{styled_connector}{styled_pattern} {full_name}"
                        )
                    else:
                        click.echo(f"{prefix}{styled_connector}{styled_pattern}")

        print_tree(resolver.url_patterns)
