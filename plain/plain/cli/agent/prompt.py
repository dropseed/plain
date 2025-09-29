import os
import shlex
import subprocess

import click


def is_agent_environment() -> bool:
    """Check if we're running inside a coding agent."""
    return bool(
        os.environ.get("CLAUDECODE")
        or os.environ.get("CODEX_SANDBOX")
        or os.environ.get("CURSOR_ENVIRONMENT")
    )


def prompt_agent(
    prompt: str, agent_command: str | None = None, print_only: bool = False
) -> bool:
    if is_agent_environment():
        click.echo(prompt)
        return True

    if print_only or not agent_command:
        click.echo(prompt)
        if not print_only:
            click.secho(
                "\nCopy the prompt above to a coding agent. To run an agent automatically, use --agent-command or set the PLAIN_AGENT_COMMAND environment variable.",
                dim=True,
                italic=True,
                err=True,
            )
        return True
    else:
        cmd = shlex.split(agent_command)
        cmd.append(prompt)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            click.secho(
                f"Agent command failed with exit code {result.returncode}",
                fg="red",
                err=True,
            )
            return False
        return True
