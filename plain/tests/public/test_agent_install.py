"""`plain agent install` copies what the installed packages ship for agents
into the project's `.claude/` directory."""

import contextlib
import os
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

from click.testing import CliRunner
from plain.cli import agent as agent_module
from plain.cli.core import cli
from plain.test import patch


@contextlib.contextmanager
def project_and_package() -> Generator[tuple[Path, Path]]:
    """A project with a `.claude/` directory, and the `agents/.claude/`
    directory of the one package it has installed. The command runs from the
    project."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        shipped = Path(tmp) / "package" / "agents" / ".claude"
        (project / ".claude").mkdir(parents=True)
        (shipped / "rules").mkdir(parents=True)
        (shipped / "skills").mkdir(parents=True)

        before = Path.cwd()
        os.chdir(project)
        try:
            with patch(agent_module, "_get_agent_dirs", lambda: [shipped]):
                yield project, shipped
        finally:
            os.chdir(before)


def install() -> str:
    result = CliRunner().invoke(cli, ["agent", "install"], prog_name="plain")
    assert result.exit_code == 0, result.output
    return result.output


def make_older(path: Path) -> None:
    an_hour_ago = time.time() - 3600
    os.utime(path, (an_hour_ago, an_hour_ago))


def test_a_rule_the_project_lacks_is_written():
    with project_and_package() as (project, shipped):
        (shipped / "rules" / "plain-cart.md").write_text("# Cart\n")

        output = install()

        assert (project / ".claude/rules/plain-cart.md").read_text() == "# Cart\n"
        assert output.splitlines() == [
            "Agent: wrote 1 in .claude/",
            "  wrote rules/plain-cart.md",
        ]


def test_a_rule_that_differs_by_one_line_is_written_though_the_projects_is_newer():
    with project_and_package() as (project, shipped):
        shipped_rule = shipped / "rules" / "plain-cart.md"
        shipped_rule.write_text("# Cart\n\n- Use helper functions.\n")
        make_older(shipped_rule)

        # What a checkout leaves: the old text, written a moment ago.
        project_rule = project / ".claude/rules/plain-cart.md"
        project_rule.parent.mkdir()
        project_rule.write_text("# Cart\n\n- Use fixtures.\n")

        output = install()

        assert project_rule.read_text() == "# Cart\n\n- Use helper functions.\n"
        assert output.splitlines() == [
            "Agent: wrote 1 in .claude/",
            "  wrote rules/plain-cart.md",
        ]


def test_a_rule_that_is_the_same_is_left_and_the_command_says_so():
    with project_and_package() as (project, shipped):
        (shipped / "rules" / "plain-cart.md").write_text("# Cart\n")
        install()
        written_at = (project / ".claude/rules/plain-cart.md").stat().st_mtime_ns

        assert install() == "Agent: up to date\n"
        after = (project / ".claude/rules/plain-cart.md").stat().st_mtime_ns
        assert after == written_at


def test_a_skill_with_one_file_that_differs_is_written_whole():
    with project_and_package() as (project, shipped):
        skill = shipped / "skills" / "plain-checkout"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# Checkout\n")
        (skill / "steps.md").write_text("1. Pay.\n")
        make_older(skill / "SKILL.md")
        make_older(skill / "steps.md")

        # The project's has the same SKILL.md, an old steps.md, and a file
        # the package no longer ships.
        installed = project / ".claude/skills/plain-checkout"
        installed.mkdir(parents=True)
        (installed / "SKILL.md").write_text("# Checkout\n")
        (installed / "steps.md").write_text("1. Ask for a card.\n")
        (installed / "gone.md").write_text("No longer shipped.\n")

        output = install()

        assert (installed / "steps.md").read_text() == "1. Pay.\n"
        assert not (installed / "gone.md").exists()
        assert output.splitlines() == [
            "Agent: wrote 1 in .claude/",
            "  wrote skills/plain-checkout",
        ]
        assert install() == "Agent: up to date\n"


def test_what_no_package_ships_any_more_is_removed_and_named():
    with project_and_package() as (project, shipped):
        (shipped / "rules" / "plain-cart.md").write_text("# Cart\n")
        rules = project / ".claude/rules"
        rules.mkdir()
        (rules / "plain-old.md").write_text("# Old\n")
        (rules / "ours.md").write_text("# The project's own\n")

        output = install()

        assert not (rules / "plain-old.md").exists()
        assert (rules / "ours.md").read_text() == "# The project's own\n"
        assert output.splitlines() == [
            "Agent: wrote 1, removed 1 in .claude/",
            "  wrote rules/plain-cart.md",
            "  removed rules/plain-old.md",
        ]
