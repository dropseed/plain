import os
import shlex
import subprocess

import click


def prompt_agent(
    prompt: str, agent_command: str | None = None, print_only: bool = False
) -> bool:
    """
    Run an agent command with the given prompt, or display the prompt for manual copying.

    Args:
        prompt: The prompt to send to the agent
        agent_command: Optional command to run (e.g., "claude code"). If not provided,
                      will check the PLAIN_AGENT_COMMAND environment variable.
        print_only: If True, always print the prompt instead of running the agent

    Returns:
        True if the agent command succeeded (or no agent command was provided),
        False if the agent command failed.
    """
    # Check if running inside an agent and just print the prompt if so
    if os.environ.get("CLAUDECODE") or os.environ.get("CODEX_SANDBOX"):
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
