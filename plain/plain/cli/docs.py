import ast
import importlib.util
import sys
from pathlib import Path

import click

from plain.packages import packages_registry


def symbolicate(file_path: Path):
    if "internal" in str(file_path).split("/"):
        return ""

    source = file_path.read_text()

    parsed = ast.parse(source)

    def should_skip(node):
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            if any(
                isinstance(d, ast.Name) and d.id == "internalcode"
                for d in node.decorator_list
            ):
                return True
            if node.name.startswith("_"):  # and not node.name.endswith("__"):
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name) and target.id.startswith("_")
                    # and not target.id.endswith("__")
                ):
                    return True
        return False

    def process_node(node, indent=0):
        lines = []
        prefix = "    " * indent

        if should_skip(node):
            return []

        if isinstance(node, ast.ClassDef):
            decorators = [
                f"{prefix}@{ast.unparse(d)}"
                for d in node.decorator_list
                if not (isinstance(d, ast.Name) and d.id == "internal")
            ]
            lines.extend(decorators)
            bases = [ast.unparse(base) for base in node.bases]
            lines.append(f"{prefix}class {node.name}({', '.join(bases)})")
            # if ast.get_docstring(node):
            #     lines.append(f'{prefix}    """{ast.get_docstring(node)}"""')
            for child in node.body:
                child_lines = process_node(child, indent + 1)
                if child_lines:
                    lines.extend(child_lines)
            # if not has_body:
            #     lines.append(f"{prefix}    pass")

        elif isinstance(node, ast.FunctionDef):
            decorators = [f"{prefix}@{ast.unparse(d)}" for d in node.decorator_list]
            lines.extend(decorators)
            args = ast.unparse(node.args)
            lines.append(f"{prefix}def {node.name}({args})")
            # if ast.get_docstring(node):
            #     lines.append(f'{prefix}    """{ast.get_docstring(node)}"""')
            # lines.append(f"{prefix}    pass")

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    lines.append(f"{prefix}{target.id} = {ast.unparse(node.value)}")

        return lines

    symbolicated_lines = []
    for node in parsed.body:
        symbolicated_lines.extend(process_node(node))

    return "\n".join(symbolicated_lines)


@click.command()
@click.option("--llm", "llm", is_flag=True)
@click.option("--open")
@click.argument("module", default="")
def docs(module, llm, open):
    if not module and not llm:
        click.secho("You must specify a module or use --llm", fg="red")
        sys.exit(1)

    if llm:
        click.echo(
            "Below is all of the documentation and abbreviated source code for the Plain web framework. "
            "Your job is to read and understand it, and then act as the Plain Framework Assistant and "
            "help the developer accomplish whatever they want to do next."
            "\n\n---\n\n"
        )

        docs = set()
        sources = set()

        # Get everything for Plain core
        for path in Path(__file__).parent.parent.glob("**/*.md"):
            docs.add(path)
        for source in Path(__file__).parent.parent.glob("**/*.py"):
            sources.add(source)

        # Find every *.md file in the other plain packages and installed apps
        for package_config in packages_registry.get_package_configs():
            if package_config.name.startswith("app."):
                # Ignore app packages for now
                continue

            for path in Path(package_config.path).glob("**/*.md"):
                docs.add(path)

            for source in Path(package_config.path).glob("**/*.py"):
                sources.add(source)

        docs = sorted(docs)
        sources = sorted(sources)

        for doc in docs:
            try:
                display_path = doc.relative_to(Path.cwd())
            except ValueError:
                display_path = doc.absolute()
            click.secho(f"<Docs: {display_path}>", fg="yellow")
            click.echo(doc.read_text())
            click.secho(f"</Docs: {display_path}>", fg="yellow")
            click.echo()

        for source in sources:
            if symbolicated := symbolicate(source):
                try:
                    display_path = source.relative_to(Path.cwd())
                except ValueError:
                    display_path = source.absolute()
                click.secho(f"<Source: {display_path}>", fg="yellow")
                click.echo(symbolicated)
                click.secho(f"</Source: {display_path}>", fg="yellow")
                click.echo()

        click.secho(
            "That's everything! Copy this into your AI tool of choice.",
            err=True,
            fg="green",
        )

        return

    if module:
        # Automatically prefix if we need to
        if not module.startswith("plain"):
            module = f"plain.{module}"

        # Get the README.md file for the module
        spec = importlib.util.find_spec(module)
        if not spec:
            click.secho(f"Module {module} not found", fg="red")
            sys.exit(1)

        module_path = Path(spec.origin).parent
        readme_path = module_path / "README.md"
        if not readme_path.exists():
            click.secho(f"README.md not found for {module}", fg="red")
            sys.exit(1)

        if open:
            click.launch(str(readme_path))
        else:

            def _iterate_markdown(content):
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

            click.echo_via_pager(_iterate_markdown(readme_path.read_text()))
