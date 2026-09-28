"""
Running the `plain test` command on a project made for one test: a project
on disk, run in its own process, judged by what it prints and how it exits.
"""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    exit_code: int
    output: str


def make_project(files: dict[str, str]) -> Path:
    # resolve(): on macOS the temp directory is a symlink, and the runner
    # prints the path it resolved.
    root = Path(tempfile.mkdtemp()).resolve()
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def run_runner(directory: Path, *arguments: str) -> CommandResult:
    """Run `python -m plain.test` from a directory."""
    completed = subprocess.run(
        [sys.executable, "-m", "plain.test", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        exit_code=completed.returncode,
        output=completed.stdout + completed.stderr,
    )


def run_in_project(files: dict[str, str], *arguments: str) -> CommandResult:
    return run_runner(make_project(files), *arguments)


def run_pasted(directory: Path, command: str, *, shell: str) -> CommandResult:
    """
    Run a command line the way pasting it into a terminal would: a shell
    reads it, and `plain` is whatever is on the PATH.
    """
    bin_directory = Path(tempfile.mkdtemp())
    plain_command = bin_directory / "plain"
    plain_command.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m plain "$@"\n')
    plain_command.chmod(0o755)

    completed = subprocess.run(
        [shell, "-c", command],
        cwd=directory,
        env={**os.environ, "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        exit_code=completed.returncode,
        output=completed.stdout + completed.stderr,
    )
