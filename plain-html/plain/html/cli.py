from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.print import print_event

from .frontmatter import split as split_frontmatter
from .loader import get_html_dirs
from .parser import ParseError, parse
from .tokenizer import TokenizeError, tokenize


@register_cli("html")
@click.group()
def cli() -> None:
    """plain.html template checks and tooling"""
    pass


@cli.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
def check(paths: tuple[Path, ...]) -> None:
    """Check .html templates for syntax and structural errors"""
    files = _collect_files(paths)
    if not files:
        click.secho("No .html templates found", fg="yellow")
        return

    print_event(f"Checking {len(files)} template(s)...")

    error_count = 0
    for path in files:
        for line in _check_file(path):
            click.echo(line)
            error_count += 1

    if error_count:
        click.secho(
            f"\n{error_count} error{'s' if error_count != 1 else ''} found",
            fg="red",
            err=True,
        )
        sys.exit(1)
    click.secho("All templates checked", fg="green")


def _collect_files(paths: tuple[Path, ...]) -> list[Path]:
    if not paths:
        return sorted(
            {f for d in get_html_dirs() if d.is_dir() for f in d.rglob("*.html")}
        )

    files: set[Path] = set()
    for p in paths:
        if p.is_file() and p.suffix == ".html":
            files.add(p)
        elif p.is_dir():
            files.update(p.rglob("*.html"))
    return sorted(files)


def _check_file(path: Path) -> list[str]:
    """Return formatted error lines for one template file."""
    source = path.read_text(encoding="utf-8")

    try:
        _, body = split_frontmatter(source)
    except Exception as e:
        return [f"{path}:1:1: frontmatter parse error: {e}"]

    body_offset = _body_offset(source)

    try:
        tokens = tokenize(body)
    except TokenizeError as e:
        return [_format_error(path, source, body_offset, e)]

    try:
        parse(tokens)
    except ParseError as e:
        return [_format_error(path, source, body_offset, e)]

    return []


_OFFSET_RE = re.compile(r"\bat offset (\d+)\b")


def _format_error(path: Path, source: str, body_offset: int, exc: Exception) -> str:
    match = _OFFSET_RE.search(str(exc))
    if match:
        line, col = _offset_to_line_col(source, body_offset + int(match.group(1)))
    else:
        line, col = 1, 1
    return f"{path}:{line}:{col}: {exc}"


def _offset_to_line_col(source: str, offset: int) -> tuple[int, int]:
    """Convert a byte offset into (1-based line, 1-based column)."""
    head = source[: max(offset, 0)]
    line = head.count("\n") + 1
    last_newline = head.rfind("\n")
    col = offset - last_newline if last_newline >= 0 else offset + 1
    return line, col


def _body_offset(source: str) -> int:
    """Return the offset within source where the template body starts.

    Mirrors python-frontmatter's `---\\n…\\n---\\n` delimiter handling so error
    positions can be mapped back to file positions even when frontmatter is
    present.
    """
    if not source.startswith("---\n"):
        return 0
    i = 4
    while i < len(source):
        end = source.find("\n", i)
        if end == -1:
            return 0
        if source[i:end].strip() == "---":
            return end + 1
        i = end + 1
    return 0
