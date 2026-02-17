from __future__ import annotations

import ast
from pathlib import Path

import click


def _is_excluded_path(path: Path, is_source: bool = False) -> bool:
    """Check if a path should be excluded from documentation."""
    path_str = str(path)

    # Exclude migrations except for plain/models/migrations
    if "/migrations/" in path_str and "/plain/models/migrations/" not in path_str:
        return True

    # Exclude agents/.claude/ content (rules, skills shipped with packages)
    if "/agents/.claude/" in path_str:
        return True

    if is_source:
        # Additional exclusions for source files
        if path.name == "cli.py" or "/cli/" in path_str:
            return True
    else:
        # Additional exclusions for docs
        if path.name in ("CHANGELOG.md", "AGENTS.md"):
            return True

    return False


def _get_node_name(node: ast.AST) -> str | None:
    """Get the name of a ClassDef, FunctionDef, or Assign node."""
    if isinstance(node, ast.ClassDef | ast.FunctionDef):
        return node.name
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id
    return None


class LLMDocs:
    """Generates LLM-friendly documentation."""

    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths

    def load(self) -> None:
        docs: set[Path] = set()
        sources: set[Path] = set()
        self.public_symbols: set[tuple[Path, str]] = set()

        for path in self.paths:
            if path.is_dir():
                docs.update(path.glob("**/*.md"))
                sources.update(path.glob("**/*.py"))
                self.public_symbols.update(self._extract_public_symbols(path))
            elif path.suffix == ".py":
                sources.add(path)
                self.public_symbols.update(self._extract_public_symbols_from_file(path))
            elif path.suffix == ".md":
                docs.add(path)

        self.docs = sorted(doc for doc in docs if not _is_excluded_path(doc))
        self.sources = sorted(
            source
            for source in sources
            if not _is_excluded_path(source, is_source=True)
        )

    def _extract_public_symbols(self, package_dir: Path) -> set[tuple[Path, str]]:
        """Extract public symbols from all __all__ in a package, tracing imports."""
        result: set[tuple[Path, str]] = set()
        for py_file in package_dir.glob("**/*.py"):
            result.update(self._extract_public_symbols_from_file(py_file))
        return result

    def _extract_public_symbols_from_file(
        self, file_path: Path
    ) -> set[tuple[Path, str]]:
        """Extract public symbols from a single file's __all__, tracing imports."""
        parsed = self._parse_file(file_path)
        if parsed is None:
            return set()

        all_names = self._get_all_names(parsed)
        if not all_names:
            return set()

        imports = self._build_import_map(parsed)
        local_definitions = self._get_local_definitions(parsed)

        result: set[tuple[Path, str]] = set()
        for name in all_names:
            if name in imports:
                module, original_name, level = imports[name]
                source_file = self._resolve_import(
                    file_path, module, original_name, level
                )
                if source_file:
                    result.add((source_file, original_name))
            elif name in local_definitions:
                result.add((file_path, name))

        return result

    @staticmethod
    def _parse_file(file_path: Path) -> ast.Module | None:
        """Parse a Python file, returning None on failure."""
        try:
            return ast.parse(file_path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            return None

    @staticmethod
    def _get_all_names(parsed: ast.Module) -> set[str]:
        """Extract names from __all__ list in a parsed module."""
        for node in parsed.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, ast.List):
                        return {
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant)
                            and isinstance(elt.value, str)
                        }
        return set()

    @staticmethod
    def _build_import_map(parsed: ast.Module) -> dict[str, tuple[str | None, str, int]]:
        """Build a map from local names to (module, original_name, level)."""
        imports: dict[str, tuple[str | None, str, int]] = {}
        for node in parsed.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    imports[local_name] = (node.module, alias.name, node.level)
        return imports

    @staticmethod
    def _get_local_definitions(parsed: ast.Module) -> set[str]:
        """Find all locally defined symbol names in a module."""
        definitions: set[str] = set()
        for node in parsed.body:
            name = _get_node_name(node)
            if name:
                definitions.add(name)
        return definitions

    def _resolve_import(
        self,
        from_file: Path,
        module: str | None,
        name: str,
        level: int,
        visited: set[Path] | None = None,
    ) -> Path | None:
        """Resolve an import to an absolute file path.

        Args:
            from_file: The file containing the import statement
            module: The module path (e.g., "db" for "from .db import x")
            name: The name being imported
            level: Import level (0=absolute, 1=relative ".", 2="..", etc.)
            visited: Set of already-visited files to prevent infinite recursion
        """
        if visited is None:
            visited = set()

        if from_file in visited:
            return None
        visited.add(from_file)

        if level > 0:
            # Relative import
            # Start from the file's directory
            base_dir = from_file.parent
            # Go up directories based on level (1 = same package, 2 = parent, etc.)
            for _ in range(level - 1):
                base_dir = base_dir.parent

            # Now resolve the module path
            if module:
                module_parts = module.split(".")
                target_dir = base_dir / Path(*module_parts)
            else:
                target_dir = base_dir

            # Could be a package (__init__.py) or a module (.py)
            if target_dir.is_dir():
                init_file = target_dir / "__init__.py"
                if init_file.exists():
                    # Check if name is re-exported from __init__.py
                    # For now, look for the actual definition file
                    return self._find_definition_in_package(target_dir, name, visited)
            else:
                py_file = target_dir.with_suffix(".py")
                if py_file.exists():
                    return py_file

        return None

    def _find_definition_in_package(
        self, package_dir: Path, name: str, visited: set[Path]
    ) -> Path | None:
        """Find where a symbol is actually defined in a package."""
        init_file = package_dir / "__init__.py"
        if not init_file.exists() or init_file in visited:
            return None

        visited.add(init_file)
        parsed = self._parse_file(init_file)
        if parsed is None:
            return None

        # Check if defined locally in __init__.py
        for node in parsed.body:
            if _get_node_name(node) == name:
                return init_file

        # Check imports in __init__.py and trace them
        for node in parsed.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    if local_name == name:
                        return self._resolve_import(
                            init_file, node.module, alias.name, node.level, visited
                        )

        return None

    @staticmethod
    def display_path(path: Path) -> Path:
        """Get a display-friendly path relative to the plain/plainx root."""
        for root_name in ("plain", "plainx"):
            if root_name in path.parts:
                root_index = path.parts.index(root_name)
                plain_root = Path(*path.parts[:root_index])
                return path.relative_to(plain_root)
        raise ValueError("Path does not contain 'plain' or 'plainx'")

    def print(
        self,
        relative_to: Path | None = None,
        include_docs: bool = True,
        include_api: bool = True,
    ) -> None:
        def get_display_path(path: Path) -> Path:
            if relative_to:
                return path.relative_to(relative_to)
            return self.display_path(path)

        if include_docs:
            for doc in self.docs:
                click.echo(doc.read_text())
                click.echo()

        if include_api:
            for source in self.sources:
                file_public_names = {
                    name for (path, name) in self.public_symbols if path == source
                }
                if not file_public_names:
                    continue
                symbolicated = self.symbolicate(source, file_public_names)
                if not symbolicated:
                    continue
                display = get_display_path(source)
                click.secho(f"<Source: {display}>", fg="yellow")
                click.echo(symbolicated)
                click.secho(f"</Source: {display}>", fg="yellow")
                click.echo()

    @staticmethod
    def symbolicate(file_path: Path, public_symbols: set[str] | None = None) -> str:
        """Generate symbolicated output for a file.

        Args:
            file_path: The Python file to process
            public_symbols: Set of symbol names that are public for this file.
                           If None, all non-private symbols are shown.
                           If empty set, nothing is shown.
        """
        if "/internal/" in str(file_path):
            return ""

        parsed = ast.parse(file_path.read_text())

        def should_skip(node: ast.AST, is_top_level: bool) -> bool:
            name = _get_node_name(node)
            if name is None:
                return True

            # Skip private symbols
            if name.startswith("_"):
                return True

            # At top level, only include symbols in the public set
            if is_top_level and public_symbols is not None:
                return name not in public_symbols

            return False

        def format_decorators(decorator_list: list[ast.expr], prefix: str) -> list[str]:
            return [f"{prefix}@{ast.unparse(d)}" for d in decorator_list]

        def process_node(node: ast.AST, indent: int = 0) -> list[str]:
            is_top_level = indent == 0
            if should_skip(node, is_top_level):
                return []

            prefix = "    " * indent
            lines: list[str] = []

            if isinstance(node, ast.ClassDef):
                lines.extend(format_decorators(node.decorator_list, prefix))
                bases = ", ".join(ast.unparse(base) for base in node.bases)
                lines.append(f"{prefix}class {node.name}({bases})")
                for child in node.body:
                    lines.extend(process_node(child, indent + 1))

            elif isinstance(node, ast.FunctionDef):
                lines.extend(format_decorators(node.decorator_list, prefix))
                args = ast.unparse(node.args)
                lines.append(f"{prefix}def {node.name}({args})")

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        lines.append(f"{prefix}{target.id} = {ast.unparse(node.value)}")

            return lines

        result_lines: list[str] = []
        for node in parsed.body:
            result_lines.extend(process_node(node))

        return "\n".join(result_lines)
