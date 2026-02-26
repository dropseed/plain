from __future__ import annotations

import importlib.machinery
import importlib.util
import re
from pathlib import Path

import click

from .llmdocs import LLMDocs

# All known official Plain packages: pip name -> short description
KNOWN_PACKAGES = {
    "plain": "Web framework core",
    "plain-admin": "Backend admin interface",
    "plain-api": "Class-based API views",
    "plain-auth": "User authentication and authorization",
    "plain-cache": "Database-backed cache with optional expiration",
    "plain-code": "Preconfigured code formatting and linting",
    "plain-dev": "Local development server with auto-reload",
    "plain-elements": "HTML template components",
    "plain-email": "Send email",
    "plain-esbuild": "Build JavaScript with esbuild",
    "plain-flags": "Feature flags via database models",
    "plain-htmx": "HTMX integration for templates and views",
    "plain-jobs": "Background jobs with a database-driven queue",
    "plain-loginlink": "Link-based authentication",
    "plain-models": "Model data and store it in a database",
    "plain-oauth": "OAuth provider login",
    "plain-observer": "On-page telemetry and observability",
    "plain-pages": "Serve static pages, markdown, and assets",
    "plain-pageviews": "Client-side pageview tracking",
    "plain-passwords": "Password authentication",
    "plain-pytest": "Test with pytest",
    "plain-redirection": "URL redirection with admin and logging",
    "plain-scan": "Test for production best practices",
    "plain-sessions": "Database-backed sessions",
    "plain-start": "Bootstrap a new project from templates",
    "plain-support": "Support forms for your application",
    "plain-tailwind": "Tailwind CSS without JavaScript or npm",
    "plain-toolbar": "Debug toolbar",
    "plain-tunnel": "Remote access to local dev server",
    "plain-vendor": "Vendor CDN scripts and styles",
}


def _discover_core_modules() -> dict[str, str]:
    """Discover core submodules within the plain package that have their own docs."""
    plain_dir = Path(__file__).resolve().parent.parent
    modules = {}
    for readme in sorted(plain_dir.glob("*/README.md")):
        name = readme.parent.name
        # Extract description from line 3 (bold subtitle pattern: **Description.**)
        lines = readme.read_text().split("\n")
        if len(lines) >= 3:
            desc = lines[2].strip().strip("*").rstrip(".")
        else:
            desc = ""
        modules[name] = desc
    return modules


def _normalize_module(module: str) -> str:
    """Normalize a module string to dotted form (e.g. plain-models -> plain.models)."""
    module = module.replace("-", ".")
    if not module.startswith("plain"):
        module = f"plain.{module}"
    return module


def _pip_package_name(module: str) -> str:
    """Convert a dotted module name to a pip package name (e.g. plain.models -> plain-models)."""
    return module.replace(".", "-")


def _is_installed(module: str) -> bool:
    """Check if a dotted module name is installed."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _online_docs_url(pip_name: str) -> str:
    """Return the online documentation URL for a package."""
    module = pip_name.replace("-", ".")
    return f"https://plainframework.com/docs/{pip_name}/{module.replace('.', '/')}/"


def _slugify(text: str) -> str:
    """Convert heading text to a URL-style slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text


def _extract_preamble(content: str) -> str | None:
    """Extract content before the first ## heading."""
    lines = content.split("\n")
    captured: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        captured.append(line)
    text = "\n".join(captured).strip()
    return text if text else None


def _extract_heading_section(
    lines: list[str],
    prefix: str,
    target_slug: str,
    stop_prefixes: list[str],
) -> str | None:
    """Extract a section starting with a heading that matches target_slug.

    Captures lines from the matching heading until a line starting with any
    of the stop_prefixes is encountered.
    """
    capturing = False
    captured: list[str] = []

    for line in lines:
        is_stop = any(line.startswith(p) for p in stop_prefixes)
        if is_stop:
            if capturing:
                break
            if (
                line.startswith(prefix)
                and _slugify(line[len(prefix) :].strip()) == target_slug
            ):
                capturing = True
                captured.append(line)
        elif capturing:
            captured.append(line)

    if captured:
        return "\n".join(captured).rstrip()

    return None


def _extract_section(content: str, target_slug: str) -> str | None:
    """Extract a ## or ### section from markdown content by its slugified heading.

    First tries to match a ## heading. If no match, tries ### headings.
    A ## section runs until the next ## heading.
    A ### section runs until the next ## or ### heading.
    """
    lines = content.split("\n")

    return _extract_heading_section(
        lines, "## ", target_slug, ["## "]
    ) or _extract_heading_section(lines, "### ", target_slug, ["## ", "### "])


def _get_section_slugs(content: str) -> list[str]:
    """Get slugified names of all ## and ### sections in markdown content."""
    slugs = []
    for line in content.split("\n"):
        for prefix in ("## ", "### "):
            if line.startswith(prefix):
                slugs.append(_slugify(line[len(prefix) :].strip()))
                break
    return slugs


def _find_namespace_readme(spec: importlib.machinery.ModuleSpec) -> Path | None:
    """Find the README.md for a namespace package by locating its pyproject.toml."""
    if not spec.submodule_search_locations:
        return None
    for p in spec.submodule_search_locations:
        path = Path(p)
        if (path.parent / "pyproject.toml").exists():
            readme = path / "README.md"
            return readme if readme.exists() else None
    return None


def _collect_all_doc_paths() -> dict[str, list[Path]]:
    """Collect README paths for all installed packages and core modules."""
    result: dict[str, list[Path]] = {}

    # Installed packages
    for pip_name in KNOWN_PACKAGES:
        dotted = pip_name.replace("-", ".")
        spec = importlib.util.find_spec(dotted)
        if spec and spec.origin:
            module_path = Path(spec.origin).parent
            llm_docs = LLMDocs([module_path])
            llm_docs.load()
            if llm_docs.docs:
                result[pip_name] = llm_docs.docs
        elif spec:
            readme = _find_namespace_readme(spec)
            if readme:
                result[pip_name] = [readme]

    # Core modules
    plain_dir = Path(__file__).resolve().parent.parent
    for name in sorted(_discover_core_modules()):
        readme = plain_dir / name / "README.md"
        if readme.exists():
            result[name] = [readme]

    return result


_TOC_LINK_RE = re.compile(r"^\s*-\s+\[.*\]\(#.*\)$")


def _is_prose(text: str) -> bool:
    """Check if a line starts with a letter (prose rather than code/symbols)."""
    return bool(text) and text[0].isalpha()


def _should_upgrade_preview(current: str, candidate: str) -> bool:
    """Return True if candidate is a better preview than current (prefer prose)."""
    return _is_prose(candidate) and not _is_prose(current)


def _search_docs(doc_paths: list[Path], pattern: re.Pattern[str]) -> dict[str, str]:
    """Search docs for matching sections.

    Returns a dict of {section_heading: first_matching_line} for each
    section that contains at least one match. Prefers prose over code for previews.
    """
    results: dict[str, str] = {}
    for doc_path in doc_paths:
        current_section = ""
        in_code_block = False
        for line in doc_path.read_text().split("\n"):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            if line.startswith("## "):
                current_section = line[3:].strip()
                if pattern.search(current_section) and current_section not in results:
                    results[current_section] = ""
                continue

            stripped = line.strip()
            if not stripped or _TOC_LINK_RE.match(stripped):
                continue

            # If this section has an empty preview, fill it with the first prose line
            if current_section in results and _should_upgrade_preview(
                results[current_section], stripped
            ):
                results[current_section] = stripped

            # Check if this line matches the search pattern
            if pattern.search(stripped):
                if current_section not in results:
                    results[current_section] = stripped
                elif _should_upgrade_preview(results[current_section], stripped):
                    results[current_section] = stripped
    return results


def _module_not_found_error(module: str) -> click.UsageError:
    """Build a UsageError for a module that could not be found or is not installed."""
    pip_name = _pip_package_name(module)
    if pip_name in KNOWN_PACKAGES:
        msg = (
            f"{module} is not installed.\n\n"
            f"  Online docs:  {_online_docs_url(pip_name)}"
        )
    else:
        msg = f"Module {module} not found. Use --list to see available packages."
    return click.UsageError(msg)


def _resolve_module_paths(module: str) -> list[Path]:
    """Resolve a dotted module name to doc paths, raising UsageError if not found."""
    spec = importlib.util.find_spec(module)

    if not spec:
        raise _module_not_found_error(module)

    if spec.origin:
        return [Path(spec.origin).parent]

    # Namespace package -- return its README if available, otherwise all search paths.
    readme = _find_namespace_readme(spec)
    if readme:
        return [readme]

    if spec.submodule_search_locations:
        return [Path(p) for p in spec.submodule_search_locations]

    raise _module_not_found_error(module)


def _print_outline(doc_paths: list[Path]) -> None:
    """Print ## and ### headings from doc files."""
    for doc_path in doc_paths:
        for line in doc_path.read_text().split("\n"):
            if line.startswith("### "):
                click.echo(f"  {click.style(line, fg='cyan')}")
            elif line.startswith("## "):
                click.secho(line, bold=True)


def _find_section_content(doc_paths: list[Path], section_heading: str) -> str | None:
    """Find and return the content of a section by heading text across multiple docs."""
    if not section_heading:
        for doc in doc_paths:
            content = _extract_preamble(doc.read_text())
            if content is not None:
                return content
        return None

    target_slug = _slugify(section_heading)
    for doc in doc_paths:
        content = _extract_section(doc.read_text(), target_slug)
        if content is not None:
            return content
    return None


@click.command()
@click.option("--api", is_flag=True, help="Show public API surface only")
@click.option("--list", "show_list", is_flag=True, help="List available packages")
@click.option("--outline", is_flag=True, help="Show section headings only")
@click.option("--search", default="", help="Search docs for a term")
@click.option("--section", default="", help="Show only a specific ## section by name")
@click.argument("module", default="")
def docs(
    module: str, api: bool, show_list: bool, outline: bool, search: str, section: str
) -> None:
    """Show documentation for a package"""
    if show_list:
        click.secho("Packages:", bold=True)
        for pip_name in sorted(KNOWN_PACKAGES):
            description = KNOWN_PACKAGES[pip_name]
            dotted = pip_name.replace("-", ".")
            installed = _is_installed(dotted)
            status = click.style(" (installed)", fg="green") if installed else ""
            click.echo(f"  {click.style(pip_name, fg='cyan')}{status} — {description}")

        click.echo()
        click.secho("Core modules:", bold=True)
        for module_name, description in _discover_core_modules().items():
            click.echo(f"  {click.style(module_name, fg='cyan')} — {description}")
        return

    # --search without module: search all installed docs
    if search and not module:
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        all_docs = _collect_all_doc_paths()
        found = False
        for name, doc_paths in sorted(all_docs.items()):
            matches = _search_docs(doc_paths, pattern)
            if matches:
                found = True
                click.secho(f"{name}:", bold=True)
                for section_heading, preview in matches.items():
                    if section_heading:
                        heading = click.style(f"## {section_heading}", fg="cyan")
                        click.echo(f"  {heading} — {preview}")
                    else:
                        click.echo(f"  {preview}")
                click.echo()
        if not found:
            click.echo(f"No results for '{search}'.")
        return

    # --outline without module: outline all installed docs
    if outline and not module:
        all_docs = _collect_all_doc_paths()
        for name, doc_paths in sorted(all_docs.items()):
            headings = []
            for doc_path in doc_paths:
                for line in doc_path.read_text().split("\n"):
                    if line.startswith("### "):
                        headings.append(f"    {click.style(line, fg='cyan')}")
                    elif line.startswith("## "):
                        headings.append(f"  {click.style(line, bold=True)}")
            if headings:
                click.secho(f"{name}:", fg="cyan", bold=True)
                for heading in headings:
                    click.echo(heading)
        return

    if not module:
        raise click.UsageError(
            "You must specify a module. Use --list to see available packages."
        )

    module = _normalize_module(module)
    module_paths = _resolve_module_paths(module)

    llm_docs = LLMDocs(module_paths)
    llm_docs.load()

    if outline:
        _print_outline(llm_docs.docs)
        return

    if search:
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        matches = _search_docs(llm_docs.docs, pattern)
        if not matches:
            click.echo(f"No results for '{search}'.")
            return
        for i, section_heading in enumerate(matches):
            content = _find_section_content(llm_docs.docs, section_heading)
            if content is not None:
                if i > 0:
                    click.echo()
                click.echo(content)
        return

    if section:
        target_slug = _slugify(section)
        available: list[str] = []
        for doc in llm_docs.docs:
            content = doc.read_text()
            section_content = _extract_section(content, target_slug)
            if section_content is not None:
                click.echo(section_content)
                return
            available.extend(_get_section_slugs(content))

        raise click.UsageError(
            f"No section matching '{section}'."
            + (f" Available: {', '.join(available)}" if available else "")
        )

    # For regular packages, show paths relative to the package parent dir.
    # For namespace packages (where module_paths[0] is a file), skip relative paths.
    if len(module_paths) == 1 and module_paths[0].is_dir():
        relative_to = module_paths[0].parent
    else:
        relative_to = None

    llm_docs.print(
        relative_to=relative_to,
        include_docs=not api,
        include_api=api,
    )
