"""A baseline in a shipped package needs one fact a reset cannot supply.

`since` names the release the reset shipped in. It is filled in by hand
when the package is released; this test is what makes forgetting fail CI.
(The package's `plain.postgres>=` minimum is raised at the same time, like
any other cross-package minimum - see the release skill.)
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def shipped_baselines() -> list[tuple[Path, str]]:
    """(migration file, since) for every baseline under `plain-*/plain/*/migrations`."""
    found: list[tuple[Path, str]] = []
    for path in sorted(REPO_ROOT.glob("plain-*/plain/*/migrations/0*.py")):
        if path.parents[3].name == "plain-postgres":
            continue  # The migration engine itself, not a package with models.
        tree = ast.parse(path.read_text())
        attributes: dict[str, str] = {}
        for node in tree.body:
            if not (isinstance(node, ast.ClassDef) and node.name == "Migration"):
                continue
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and isinstance(statement.value, ast.Constant)
                ):
                    attributes[statement.targets[0].id] = str(statement.value.value)
        if attributes.get("supersedes"):
            found.append((path, attributes.get("since", "")))
    return found


def test_shipped_baselines_are_stamped() -> None:
    problems = []
    for path, since in shipped_baselines():
        package_dir = path.parents[3]
        relative = path.relative_to(REPO_ROOT)
        if not since:
            problems.append(
                f"{relative}: `since` is empty - set it to the {package_dir.name} "
                "version this reset ships in."
            )
    assert not problems, "\n".join(problems)
