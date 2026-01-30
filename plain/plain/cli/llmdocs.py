from __future__ import annotations

import ast
from pathlib import Path

import click


class LLMDocs:
    """Generates LLM-friendly documentation."""

    def __init__(self, paths: list[Path]):
        self.paths = paths

    def load(self) -> None:
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
        # Also exclude CHANGELOG.md, AGENTS.md, and agents directory
        self.docs = {
            doc
            for doc in self.docs
            if not (
                "/migrations/" in str(doc)
                and "/plain/models/migrations/" not in str(doc)
            )
            and doc.name not in ("CHANGELOG.md", "AGENTS.md")
            and "/agents/" not in str(doc)
        }
        self.sources = {
            source
            for source in self.sources
            if not (
                "/migrations/" in str(source)
                and "/plain/models/migrations/" not in str(source)
            )
            and source.name != "cli.py"
            and "/agents/" not in str(source)
        }

        self.docs = sorted(self.docs)
        self.sources = sorted(self.sources)

    def display_path(self, path: Path) -> Path:
        if "plain" in path.parts:
            root_index = path.parts.index("plain")
        elif "plainx" in path.parts:
            root_index = path.parts.index("plainx")
        else:
            raise ValueError("Path does not contain 'plain' or 'plainx'")

        plain_root = Path(*path.parts[: root_index + 1])
        return path.relative_to(plain_root.parent)

    def print(
        self,
        relative_to: Path | None = None,
        include_docs: bool = True,
        include_symbols: bool = True,
    ) -> None:
        if include_docs:
            for doc in self.docs:
                if relative_to:
                    display_path = doc.relative_to(relative_to)
                else:
                    display_path = self.display_path(doc)
                click.secho(f"<Docs: {display_path}>", fg="yellow")
                click.echo(doc.read_text())
                click.secho(f"</Docs: {display_path}>", fg="yellow")
                click.echo()

        if include_symbols:
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
    def symbolicate(file_path: Path) -> str:
        if "internal" in str(file_path).split("/"):
            return ""

        source = file_path.read_text()

        parsed = ast.parse(source)

        def should_skip(node: ast.AST) -> bool:
            if isinstance(node, ast.ClassDef):
                if any(
                    isinstance(d, ast.Name) and d.id == "internalcode"
                    for d in node.decorator_list
                ):
                    return True
                if node.name.startswith("_"):
                    return True
            elif isinstance(node, ast.FunctionDef):
                if any(
                    isinstance(d, ast.Name) and d.id == "internalcode"
                    for d in node.decorator_list
                ):
                    return True
                if node.name.startswith("_"):
                    return True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.startswith("_"):
                        return True
            return False

        def process_node(node: ast.AST, indent: int = 0) -> list[str]:
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
                for child in node.body:
                    child_lines = process_node(child, indent + 1)
                    if child_lines:
                        lines.extend(child_lines)

            elif isinstance(node, ast.FunctionDef):
                decorators = [f"{prefix}@{ast.unparse(d)}" for d in node.decorator_list]
                lines.extend(decorators)
                args = ast.unparse(node.args)
                lines.append(f"{prefix}def {node.name}({args})")

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        lines.append(f"{prefix}{target.id} = {ast.unparse(node.value)}")

            return lines

        symbolicated_lines = []
        for node in parsed.body:
            symbolicated_lines.extend(process_node(node))

        return "\n".join(symbolicated_lines)
