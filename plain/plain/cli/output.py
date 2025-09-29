from __future__ import annotations

from collections.abc import Iterator

import click


def style_markdown(content: str) -> str:
    return "".join(iterate_markdown(content))


def iterate_markdown(content: str) -> Iterator[str]:
    """
    Iterator that does basic markdown for a Click pager.

    Headings are yellow and bright, code blocks are indented.
    """

    in_code_block = False
    for line in content.splitlines():
        if line.startswith("```"):
            in_code_block = not in_code_block

        if in_code_block:
            yield click.style(line, dim=True)
        elif line.startswith("# "):
            yield click.style(line, fg="yellow", bold=True)
        elif line.startswith("## "):
            yield click.style(line, fg="yellow", bold=True)
        elif line.startswith("### "):
            yield click.style(line, fg="yellow", bold=True)
        elif line.startswith("#### "):
            yield click.style(line, fg="yellow", bold=True)
        elif line.startswith("##### "):
            yield click.style(line, fg="yellow", bold=True)
        elif line.startswith("###### "):
            yield click.style(line, fg="yellow", bold=True)
        elif line.startswith("**") and line.endswith("**"):
            yield click.style(line, bold=True)
        elif line.startswith("> "):
            yield click.style(line, italic=True)
        else:
            yield line

        yield "\n"
