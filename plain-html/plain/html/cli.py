from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.print import print_event

from .format import format_source
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
@click.argument("paths", nargs=-1)
def check(paths: tuple[str, ...]) -> None:
    """Check .html templates for syntax and structural errors

    Pass `-` to read source from stdin; errors print to stderr as
    `<stdin>:line:col: message`.
    """
    if "-" in paths:
        if len(paths) != 1:
            raise click.UsageError("Cannot mix `-` with other paths")
        _check_stdin()
        return

    files = _collect_files(_paths_to_paths(paths))
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


def _check_stdin() -> None:
    source = sys.stdin.read()
    body_offset = _body_offset(source)

    try:
        _, body = split_frontmatter(source)
    except Exception as e:
        click.echo(f"<stdin>:1:1: frontmatter parse error: {e}", err=True)
        sys.exit(1)

    try:
        tokens = tokenize(body)
    except TokenizeError as e:
        click.echo(
            _format_error_with_label("<stdin>", source, body_offset, e), err=True
        )
        sys.exit(1)

    try:
        parse(tokens)
    except ParseError as e:
        click.echo(
            _format_error_with_label("<stdin>", source, body_offset, e), err=True
        )
        sys.exit(1)


def _paths_to_paths(paths: tuple[str, ...]) -> tuple[Path, ...]:
    """Validate string paths exist and convert to Path. Mirrors click's
    `Path(exists=True)` behavior — moved into the command so we can
    handle `-` (stdin) before validation kicks in."""
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            raise click.BadParameter(f"Path {p!r} does not exist")
        out.append(path)
    return tuple(out)


@cli.command(name="format")
@click.argument("paths", nargs=-1)
@click.option(
    "--check",
    "check_only",
    is_flag=True,
    help="Exit non-zero if files would change; do not write",
)
def format_cmd(paths: tuple[str, ...], check_only: bool) -> None:
    """Format .html templates in place

    Pass `-` to read source from stdin and write the formatted output to
    stdout. With `--check`, exit 0 if no change, 1 if would change.
    """
    if "-" in paths:
        if len(paths) != 1:
            raise click.UsageError("Cannot mix `-` with other paths")
        _format_stdin(check_only=check_only)
        return

    files = _collect_files(_paths_to_paths(paths))
    if not files:
        click.secho("No .html templates found", fg="yellow")
        return

    print_event(f"Formatting {len(files)} template(s)...")

    changed: list[Path] = []
    skipped: list[tuple[Path, Exception]] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        try:
            out = format_source(source)
        except (TokenizeError, ParseError) as e:
            skipped.append((path, e))
            continue
        if out != source:
            changed.append(path)
            if not check_only:
                path.write_text(out, encoding="utf-8")

    for path, exc in skipped:
        click.echo(f"{path}: skipped — {exc}", err=True)

    verb = "would reformat" if check_only else "reformatted"
    for path in changed:
        click.echo(f"{verb}: {path}")

    if check_only and changed:
        click.secho(
            f"\n{len(changed)} file{'s' if len(changed) != 1 else ''} would be reformatted",
            fg="red",
            err=True,
        )
        sys.exit(1)

    if not check_only:
        unchanged = len(files) - len(changed) - len(skipped)
        click.secho(
            f"\n{len(changed)} reformatted, {unchanged} unchanged"
            + (f", {len(skipped)} skipped" if skipped else ""),
            fg="green" if not skipped else "yellow",
        )
        if skipped:
            sys.exit(1)
    elif not changed:
        click.secho("All templates already formatted", fg="green")


def _format_stdin(*, check_only: bool) -> None:
    source = sys.stdin.read()
    try:
        out = format_source(source)
    except (TokenizeError, ParseError) as e:
        click.echo(f"<stdin>: {e}", err=True)
        sys.exit(1)

    if check_only:
        sys.exit(0 if out == source else 1)

    sys.stdout.write(out)


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
        return [_format_error_with_label(str(path), source, body_offset, e)]

    try:
        parse(tokens)
    except ParseError as e:
        return [_format_error_with_label(str(path), source, body_offset, e)]

    return []


_OFFSET_RE = re.compile(r"\bat offset (\d+)\b")


def _format_error_with_label(
    label: str, source: str, body_offset: int, exc: Exception
) -> str:
    match = _OFFSET_RE.search(str(exc))
    if match:
        line, col = _offset_to_line_col(source, body_offset + int(match.group(1)))
    else:
        line, col = 1, 1
    return f"{label}:{line}:{col}: {exc}"


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
