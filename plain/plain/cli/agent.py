import shlex
import subprocess

import click


def prompt_agent(prompt: str, agent_command: str | None = None) -> bool:
    """
    Run an agent command with the given prompt, or display the prompt for manual copying.

    Args:
        prompt: The prompt to send to the agent
        agent_command: Optional command to run (e.g., "claude code"). If not provided,
                      will check the PLAIN_AGENT_COMMAND environment variable.

    Returns:
        True if the agent command succeeded (or no agent command was provided),
        False if the agent command failed.
    """
    if agent_command:
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
    else:
        click.echo(prompt)
        click.secho(
            "\nCopy the prompt above to a coding agent. To run an agent automatically, use --agent-command or set the PLAIN_AGENT_COMMAND environment variable.",
            dim=True,
            italic=True,
            err=True,
        )
        return True
