"""
Type annotation analyzer for Python codebases.

Analyzes Python files to determine the percentage of functions/methods
that have complete type annotations (parameters and return types).
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path


@dataclass
class FunctionInfo:
    """Information about a function/method for type checking."""

    name: str
    file: str
    line: int
    is_method: bool = False
    has_return_type: bool = False
    total_params: int = 0
    typed_params: int = 0
    is_property: bool = False

    @property
    def is_fully_typed(self) -> bool:
        """Check if function has all type annotations."""
        return self.has_return_type and (self.typed_params == self.total_params)


@dataclass
class FileStats:
    """Statistics for a single Python file."""

    path: str
    functions: list[FunctionInfo] = field(default_factory=list)
    ignore_comments: int = 0
    cast_calls: int = 0
    assert_statements: int = 0

    @property
    def total_functions(self) -> int:
        return len(self.functions)

    @property
    def fully_typed_functions(self) -> int:
        return sum(1 for f in self.functions if f.is_fully_typed)

    @property
    def missing_functions(self) -> int:
        return self.total_functions - self.fully_typed_functions


class TypeAnnotationAnalyzer(ast.NodeVisitor):
    """AST visitor to analyze type annotations in Python code."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.functions: list[FunctionInfo] = []
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track when we enter/exit a class."""
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Analyze function definitions."""
        self._analyze_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Analyze async function definitions."""
        self._analyze_function(node)
        self.generic_visit(node)

    def _analyze_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Analyze a function/method for type annotations."""
        # Skip __init__ return type check (it's always None implicitly)
        is_init = node.name == "__init__"

        # Check if it's a method (inside a class)
        is_method = bool(self.class_stack)

        # Check decorators
        is_property = any(
            (isinstance(d, ast.Name) and d.id == "property")
            or (isinstance(d, ast.Attribute) and d.attr == "property")
            for d in node.decorator_list
        )

        # Create function info
        func_info = FunctionInfo(
            name=node.name,
            file=self.file_path,
            line=node.lineno,
            is_method=is_method,
            is_property=is_property,
        )

        # Check return type (not needed for __init__)
        if not is_init:
            func_info.has_return_type = node.returns is not None
        else:
            func_info.has_return_type = True

        def handle_param(arg: ast.arg) -> None:
            if is_method and arg.arg in {"self", "cls"}:
                return

            func_info.total_params += 1
            if arg.annotation is not None:
                func_info.typed_params += 1

        # Analyze parameters
        for arg in node.args.posonlyargs:
            handle_param(arg)

        for arg in node.args.args:
            handle_param(arg)

        for arg in node.args.kwonlyargs:
            handle_param(arg)

        # Check *args and **kwargs
        if node.args.vararg:
            func_info.total_params += 1
            if node.args.vararg.annotation is not None:
                func_info.typed_params += 1

        if node.args.kwarg:
            func_info.total_params += 1
            if node.args.kwarg.annotation is not None:
                func_info.typed_params += 1

        self.functions.append(func_info)


def count_ignore_comments(content: str) -> int:
    """Count type: ignore comments in the file."""
    count = 0
    pattern = r"#\s*type:\s*ignore"

    for line in content.split("\n"):
        if re.search(pattern, line, re.IGNORECASE):
            count += 1

    return count


def count_cast_calls(content: str) -> int:
    """Count cast() function calls in the file."""
    # Match both 'cast(' and 'typing.cast('
    patterns = [
        r"\bcast\s*\(",
        r"\btyping\.cast\s*\(",
    ]

    count = 0
    for line in content.split("\n"):
        for pattern in patterns:
            count += len(re.findall(pattern, line))

    return count


class AssertCounter(ast.NodeVisitor):
    """AST visitor to count assert statements."""

    def __init__(self) -> None:
        self.count = 0

    def visit_Assert(self, node: ast.Assert) -> None:
        self.count += 1
        self.generic_visit(node)


def count_assert_statements(tree: ast.AST) -> int:
    """Count assert statements in the AST."""
    counter = AssertCounter()
    counter.visit(tree)
    return counter.count


def analyze_file(file_path: Path) -> FileStats | None:
    """Analyze a single Python file for type annotations."""
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content, filename=str(file_path))
        analyzer = TypeAnnotationAnalyzer(str(file_path))
        analyzer.visit(tree)

        ignore_count = count_ignore_comments(content)
        cast_count = count_cast_calls(content)
        assert_count = count_assert_statements(tree)

        stats = FileStats(
            path=str(file_path),
            functions=analyzer.functions,
            ignore_comments=ignore_count,
            cast_calls=cast_count,
            assert_statements=assert_count,
        )
        return stats

    except (SyntaxError, UnicodeDecodeError):
        return None


def find_python_files(
    directory: Path, exclude_patterns: list[str] | None = None
) -> list[Path]:
    """Find all Python files in a directory, excluding certain patterns."""
    default_patterns = [
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "env",
        ".tox",
        "build",
        "dist",
        "*.egg-info",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        # Exclude test files from annotation metrics
        "test_*.py",
        "*_test.py",
        "tests",
        "test",
    ]

    patterns = list(default_patterns)
    if exclude_patterns:
        patterns.extend(exclude_patterns)

    def should_exclude(path: Path) -> bool:
        try:
            relative = path.relative_to(directory).as_posix()
        except ValueError:
            relative = path.as_posix()

        candidates = {relative, path.as_posix(), path.name}
        for pattern in patterns:
            if any(fnmatch(candidate, pattern) for candidate in candidates):
                return True
        return False

    python_files = []

    for root, dirs, files in os.walk(directory):
        # Filter out excluded directories
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not should_exclude(root_path / d)]

        for file in files:
            if file.endswith(".py"):
                file_path = root_path / file
                # Check if file path matches excluded patterns
                if not should_exclude(file_path):
                    python_files.append(file_path)

    return python_files


@dataclass
class AnnotationResult:
    """Result of annotation analysis."""

    total_functions: int
    fully_typed_functions: int
    missing_count: int
    total_ignores: int
    total_casts: int
    total_asserts: int
    file_stats: list[FileStats]

    @property
    def coverage_percentage(self) -> float:
        if self.total_functions == 0:
            return 100.0
        return (self.fully_typed_functions / self.total_functions) * 100


def check_annotations(
    path: str, exclude_patterns: list[str] | None = None
) -> AnnotationResult:
    """Check type annotations in the given path."""
    target = Path(path)

    if target.is_file():
        if not target.suffix == ".py":
            return AnnotationResult(
                total_functions=0,
                fully_typed_functions=0,
                missing_count=0,
                total_ignores=0,
                total_casts=0,
                total_asserts=0,
                file_stats=[],
            )
        python_files = [target]
    elif target.is_dir():
        python_files = find_python_files(target, exclude_patterns)
    else:
        return AnnotationResult(
            total_functions=0,
            fully_typed_functions=0,
            missing_count=0,
            total_ignores=0,
            total_casts=0,
            total_asserts=0,
            file_stats=[],
        )

    all_stats = []
    for file_path in python_files:
        stats = analyze_file(file_path)
        if stats:
            all_stats.append(stats)

    total_functions = sum(s.total_functions for s in all_stats)
    fully_typed_functions = sum(s.fully_typed_functions for s in all_stats)
    total_ignores = sum(s.ignore_comments for s in all_stats)
    total_casts = sum(s.cast_calls for s in all_stats)
    total_asserts = sum(s.assert_statements for s in all_stats)

    return AnnotationResult(
        total_functions=total_functions,
        fully_typed_functions=fully_typed_functions,
        missing_count=total_functions - fully_typed_functions,
        total_ignores=total_ignores,
        total_casts=total_casts,
        total_asserts=total_asserts,
        file_stats=all_stats,
    )
