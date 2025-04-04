import ast
import importlib.util
import sys
from pathlib import Path

import click

from plain.packages import packages_registry


@click.command()
@click.option("--llm", "llm", is_flag=True)
@click.option("--open")
@click.argument("module", default="")
def docs(module, llm, open):
    if not module and not llm:
        click.secho("You must specify a module or use --llm", fg="red")
        sys.exit(1)

    if llm:
        paths = [Path(__file__).parent.parent]

        for package_config in packages_registry.get_package_configs():
            if package_config.name.startswith("app."):
                # Ignore app packages for now
                continue

            paths.append(Path(package_config.path))

        source_docs = LLMDocs(paths)
        source_docs.load()
        source_docs.print()

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


class LLMDocs:
    preamble = (
        "Below is all of the documentation and abbreviated source code for the Plain web framework. "
        "Your job is to read and understand it, and then act as the Plain Framework Assistant and "
        "help the developer accomplish whatever they want to do next."
        "\n\n---\n\n"
    )

    def __init__(self, paths):
        self.paths = paths

    def load(self):
        self.docs = set()
        self.sources = set()

        for path in self.paths:
            if path.is_dir():
                self.docs.update(path.glob("**/*.md"))
                self.sources.update(path.glob("**/*.py"))
            elif path.suffix == ".py":
                self.sources.add(path)
            elif path.suffix == ".md":
                self.docs.add(path)

        # Exclude "migrations" code from plain apps, except for plain/models/migrations
        self.docs = {
            doc
            for doc in self.docs
            if not (
                "/migrations/" in str(doc)
                and "/plain/models/migrations/" not in str(doc)
            )
        }
        self.sources = {
            source
            for source in self.sources
            if not (
                "/migrations/" in str(source)
                and "/plain/models/migrations/" not in str(source)
            )
        }

        self.docs = sorted(self.docs)
        self.sources = sorted(self.sources)

    def display_path(self, path):
        if "plain" in path.parts:
            root_index = path.parts.index("plain")
        elif "plainx" in path.parts:
            root_index = path.parts.index("plainx")
        else:
            raise ValueError("Path does not contain 'plain' or 'plainx'")

        plain_root = Path(*path.parts[: root_index + 1])
        return path.relative_to(plain_root.parent)

    def print(self, relative_to=None):
        click.secho(self.preamble, fg="yellow")

        for doc in self.docs:
            if relative_to:
                display_path = doc.relative_to(relative_to)
            else:
                display_path = self.display_path(doc)
            click.secho(f"<Docs: {display_path}>", fg="yellow")
            click.echo(doc.read_text())
            click.secho(f"</Docs: {display_path}>", fg="yellow")
            click.echo()

        for source in self.sources:
            if symbolicated := self.symbolicate(source):
                if relative_to:
                    display_path = source.relative_to(relative_to)
                else:
                    display_path = self.display_path(source)
                click.secho(f"<Source: {display_path}>", fg="yellow")
                click.echo(symbolicated)
                click.secho(f"</Source: {display_path}>", fg="yellow")
                click.echo()

    @staticmethod
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
                    if not (isinstance(d, ast.Name) and d.id == "internalcode")
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
