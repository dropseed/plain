from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.print import print_event

from . import _cache
from .compiler import CompileError, CompileSession, clear_process_cache
from .format import format_source
from .frontmatter import split as split_frontmatter
from .loader import get_html_dirs
from .parser import ParseError, parse
from .positions import body_offset, offset_to_line_col
from .tokenizer import TokenizeError, tokenize
from .typecheck import check_path as typecheck_path
from .typecheck import check_source as typecheck_source
from .typecheck.backends import BackendError
from .typecheck.backends import resolve as resolve_backend
from .typecheck.declarations import DeclarationError
from .typecheck.declarations import parse as parse_declarations


@register_cli("html")
@click.group()
def cli() -> None:
    """plain.html template checks and tooling"""
    pass


@cli.command()
@click.argument("paths", nargs=-1)
@click.option(
    "--typecheck",
    "-t",
    "run_typecheck",
    is_flag=True,
    help="Also type-check `{expr}` against the template's `attrs:` / `imports:`",
)
@click.option(
    "--backend",
    "backend_name",
    default=None,
    help="Typecheck backend to use (default: ty; pyright also supported).",
)
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    help="Skip the typecheck result cache (full subprocess run every file)",
)
@click.option(
    "--include-installed-packages",
    "include_installed_packages",
    is_flag=True,
    hidden=True,
    help=(
        "Also check templates shipped by installed Plain packages "
        "(plain.admin, plain.toolbar, …). For framework / package "
        "development only — end-user projects should leave this off."
    ),
)
def check(
    paths: tuple[str, ...],
    run_typecheck: bool,
    backend_name: str | None,
    no_cache: bool,
    include_installed_packages: bool,
) -> None:
    """Check .html templates for syntax and structural errors

    Pass `-` to read source from stdin; errors print to stderr as
    `<stdin>:line:col: message`. Add `--typecheck` to also run the
    template's `{expr}` content through the configured Python type
    checker (ty by default).
    """
    if "-" in paths:
        if len(paths) != 1:
            raise click.UsageError("Cannot mix `-` with other paths")
        _check_stdin(
            run_typecheck=run_typecheck,
            backend_name=backend_name,
            use_cache=not no_cache,
        )
        return

    files = _collect_files(
        _paths_to_paths(paths),
        include_installed_packages=include_installed_packages,
    )
    if not files:
        click.secho("No .html templates found", fg="yellow")
        return

    if include_installed_packages and not paths:
        click.secho(
            "Note: also checking templates shipped by installed Plain packages. "
            "Those are owned by their packages — report problems upstream rather "
            "than editing locally.",
            fg="yellow",
            err=True,
        )

    print_event(f"Checking {len(files)} template(s)...")

    backend = None
    if run_typecheck:
        try:
            backend = resolve_backend(backend_name)
        except BackendError as e:
            click.secho(str(e), fg="red", err=True)
            sys.exit(2)

    error_count = 0
    for path in files:
        for line in _check_file(path):
            click.echo(line)
            error_count += 1
        if run_typecheck and backend is not None:
            try:
                results = typecheck_path(path, backend=backend, use_cache=not no_cache)
            except BackendError as e:
                click.echo(f"{path}: typecheck error: {e}", err=True)
                error_count += 1
                continue
            for err in results:
                click.echo(err.format())
                error_count += 1

    if error_count:
        click.secho(
            f"\n{error_count} error{'s' if error_count != 1 else ''} found",
            fg="red",
            err=True,
        )
        sys.exit(1)
    click.secho("All templates checked", fg="green")


def _check_stdin(
    *,
    run_typecheck: bool = False,
    backend_name: str | None = None,
    use_cache: bool = True,
) -> None:
    source = sys.stdin.read()
    body_start = body_offset(source)

    try:
        fmdict, body = split_frontmatter(source)
    except Exception as e:
        click.echo(f"<stdin>:1:1: frontmatter parse error: {e}", err=True)
        sys.exit(1)

    try:
        parse_declarations(fmdict)
    except DeclarationError as e:
        click.echo(f"<stdin>:1:1: {e}", err=True)
        sys.exit(1)

    try:
        tokens = tokenize(body)
    except TokenizeError as e:
        click.echo(
            _format_error_with_label("<stdin>", source, body_start, e), err=True
        )
        sys.exit(1)

    try:
        parse(tokens)
    except ParseError as e:
        click.echo(
            _format_error_with_label("<stdin>", source, body_start, e), err=True
        )
        sys.exit(1)

    if run_typecheck:
        try:
            backend = resolve_backend(backend_name)
            results = typecheck_source(source, backend=backend, use_cache=use_cache)
        except BackendError as e:
            click.echo(f"<stdin>: typecheck error: {e}", err=True)
            sys.exit(1)
        if results:
            for err in results:
                click.echo(err.format(), err=True)
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
@click.option(
    "--include-installed-packages",
    "include_installed_packages",
    is_flag=True,
    hidden=True,
    help=(
        "Also format templates shipped by installed Plain packages. "
        "For framework / package development only."
    ),
)
def format_cmd(
    paths: tuple[str, ...],
    check_only: bool,
    include_installed_packages: bool,
) -> None:
    """Format .html templates in place

    Pass `-` to read source from stdin and write the formatted output to
    stdout. With `--check`, exit 0 if no change, 1 if would change.
    """
    if "-" in paths:
        if len(paths) != 1:
            raise click.UsageError("Cannot mix `-` with other paths")
        _format_stdin(check_only=check_only)
        return

    files = _collect_files(
        _paths_to_paths(paths),
        include_installed_packages=include_installed_packages,
    )
    if not files:
        click.secho("No .html templates found", fg="yellow")
        return

    if include_installed_packages and not paths:
        click.secho(
            "Note: also formatting templates shipped by installed Plain packages. "
            "Those are owned by their packages — changes will be lost on the "
            "next package upgrade.",
            fg="yellow",
            err=True,
        )

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


@cli.command(name="compile")
@click.argument("paths", nargs=-1)
@click.option(
    "--include-installed-packages",
    "include_installed_packages",
    is_flag=True,
    hidden=True,
    help=(
        "Also compile templates shipped by installed Plain packages. "
        "For framework / package development only."
    ),
)
def compile_cmd(paths: tuple[str, ...], include_installed_packages: bool) -> None:
    """Pre-compile .html templates into the on-disk cache

    Warms `<project>/.plain/html/` (or `$PLAIN_HTML_CACHE_DIR`) so the
    first render of each template in production doesn't pay codegen
    cost. Run during deploy after templates are in place.
    """
    files = _collect_files(
        _paths_to_paths(paths),
        include_installed_packages=include_installed_packages,
    )
    if not files:
        click.secho("No .html templates found", fg="yellow")
        return

    cache_dir = _cache.cache_root()
    if cache_dir is None:
        click.secho(
            "Cache is disabled (PLAIN_HTML_CACHE_DIR is empty). "
            "Set the env var or unset it to use the default location.",
            fg="red",
            err=True,
        )
        sys.exit(2)

    print_event(f"Compiling {len(files)} template(s) to {cache_dir}...")

    # Don't share the in-memory process cache across runs of this command —
    # we want every template to write its disk file even if a previous
    # invocation populated the in-memory cache for it.
    clear_process_cache()

    ok = 0
    skipped: list[tuple[Path, Exception]] = []
    for path in files:
        try:
            CompileSession(use_disk_cache=True).compile_path(path)
            ok += 1
        except (CompileError, ParseError, TokenizeError) as e:
            skipped.append((path, e))

    for path, exc in skipped:
        click.echo(f"{path}: skipped — {exc}", err=True)

    click.secho(
        f"\n{ok} compiled, {len(skipped)} skipped",
        fg="green" if not skipped else "yellow",
    )
    if skipped:
        sys.exit(1)


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


def _collect_files(
    paths: tuple[Path, ...], *, include_installed_packages: bool = False
) -> list[Path]:
    if not paths:
        # Default: only the project's own `app/html/`. Installed-package
        # templates are owned by their packages — checking them produces
        # diagnostics the end user can't act on. The
        # `--include-installed-packages` flag opts in for framework /
        # package development.
        if include_installed_packages:
            dirs = [d for d in get_html_dirs() if d.is_dir()]
        else:
            app_html, *_ = get_html_dirs()
            dirs = [app_html] if app_html.is_dir() else []
        return sorted({f for d in dirs for f in d.rglob("*.html")})

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
        fmdict, body = split_frontmatter(source)
    except Exception as e:
        return [f"{path}:1:1: frontmatter parse error: {e}"]

    try:
        parse_declarations(fmdict)
    except DeclarationError as e:
        return [f"{path}:1:1: {e}"]

    body_start = body_offset(source)

    try:
        tokens = tokenize(body)
    except TokenizeError as e:
        return [_format_error_with_label(str(path), source, body_start, e)]

    try:
        parse(tokens)
    except ParseError as e:
        return [_format_error_with_label(str(path), source, body_start, e)]

    return []


_OFFSET_RE = re.compile(r"\bat offset (\d+)\b")


def _format_error_with_label(
    label: str, source: str, body_start: int, exc: Exception
) -> str:
    match = _OFFSET_RE.search(str(exc))
    if match:
        line, col = offset_to_line_col(source, body_start + int(match.group(1)))
    else:
        line, col = 1, 1
    return f"{label}:{line}:{col}: {exc}"
