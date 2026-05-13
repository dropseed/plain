from __future__ import annotations

from collections.abc import Iterator

import click


@click.group()
def urls() -> None:
    """URL configuration commands"""


@urls.command("list")
@click.option("--flat", is_flag=True, help="List all URLs in a flat list")
def list_urls(flat: bool) -> None:
    """List all URL patterns"""
    from plain.runtime import settings
    from plain.urls import URLPattern, URLResolver, get_resolver
    from plain.urls.segments import Segment, _route_str

    if not settings.URLS_ROUTER:
        raise click.UsageError("URLS_ROUTER is not set")

    resolver = get_resolver(settings.URLS_ROUTER)
    if flat:

        def flat_list(
            patterns: list[URLPattern | URLResolver],
            prefix_segments: tuple[Segment, ...] = (),
            curr_ns: str = "",
        ) -> Iterator[str]:
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    new_ns = (
                        f"{curr_ns}:{pattern.namespace}"
                        if curr_ns and pattern.namespace
                        else (pattern.namespace or curr_ns)
                    )
                    yield from flat_list(
                        pattern.url_patterns,
                        prefix_segments=prefix_segments + pattern.segments,
                        curr_ns=new_ns,
                    )
                else:
                    full_segments = prefix_segments + pattern.segments
                    # Root URL (`path("")` at top level) has no slash variant.
                    if not full_segments:
                        full_pattern = "/"
                    else:
                        full_pattern = _route_str(full_segments, pattern.trailing_slash)
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

        def print_tree(
            patterns: list[URLPattern | URLResolver],
            prefix: str = "",
            curr_ns: str = "",
        ) -> None:
            count = len(patterns)
            for idx, pattern in enumerate(patterns):
                is_last = idx == (count - 1)
                connector = "└── " if is_last else "├── "
                styled_connector = click.style(connector)
                # Show the endpoint's own canonical slash so the tree
                # reflects what `resolve()`/`reverse()` actually produce.
                # Includes show their bare prefix — the tree's hierarchy
                # already implies the separator to children.
                if isinstance(pattern, URLPattern) and pattern.trailing_slash:
                    label = f"{pattern.raw_route}/"
                else:
                    label = pattern.raw_route
                styled_pattern = click.style(label)
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
