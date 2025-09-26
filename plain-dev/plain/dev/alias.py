import os
import subprocess
import sys
from functools import cached_property
from pathlib import Path

import click


class AliasManager:
    """Manages the 'p' alias for 'uv run plain'."""

    MARKER_FILE = Path.home() / ".plain" / "dev" / ".alias_prompted"
    ALIAS_COMMAND = "uv run plain"
    ALIAS_NAME = "p"

    @cached_property
    def shell(self):
        """Detect the current shell."""
        shell = os.environ.get("SHELL", "")
        if "zsh" in shell:
            return "zsh"
        elif "bash" in shell:
            return "bash"
        elif "fish" in shell:
            return "fish"
        return None

    @cached_property
    def shell_config_file(self):
        """Get the appropriate shell configuration file."""
        home = Path.home()

        if self.shell == "zsh":
            return home / ".zshrc"
        elif self.shell == "bash":
            # Check for .bash_aliases first (Ubuntu/Debian convention)
            if (home / ".bash_aliases").exists():
                return home / ".bash_aliases"
            return home / ".bashrc"
        elif self.shell == "fish":
            return home / ".config" / "fish" / "config.fish"

        return None

    def _command_exists(self, command):
        """Check if a command exists in the system."""
        try:
            result = subprocess.run(
                ["which", command], capture_output=True, text=True, check=False
            )
            return result.returncode == 0
        except Exception:
            return False

    def _alias_exists(self):
        """Check if the 'p' alias already exists."""
        # First check if 'p' is already a command
        if self._command_exists(self.ALIAS_NAME):
            return True

        # Check if alias is defined in shell
        try:
            # Try to run the alias to see if it exists
            result = subprocess.run(
                [self.shell, "-i", "-c", f"alias {self.ALIAS_NAME}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            return False

    def _add_alias_to_shell(self):
        """Add the alias to the shell configuration file."""
        if not self.shell_config_file or not self.shell_config_file.exists():
            return False

        alias_line = f'alias {self.ALIAS_NAME}="{self.ALIAS_COMMAND}"'
        comment = "# Added by Plain"

        # Check if alias already in file
        try:
            with open(self.shell_config_file) as f:
                content = f.read()
                if alias_line in content:
                    return True
        except Exception:
            return False

        # Add alias to file
        try:
            with open(self.shell_config_file, "a") as f:
                f.write(f"\n{comment}\n{alias_line}\n")

            click.secho(
                f"✓ Added '{self.ALIAS_NAME}' alias to {self.shell_config_file.name}. Restart your shell!",
                fg="green",
            )
            return True
        except Exception as e:
            click.secho(
                f"Failed to add alias to {self.shell_config_file.name}: {e}", fg="red"
            )
            return False

    def check_and_prompt(self):
        """Check if alias exists and prompt user to set it up if needed."""
        # Only suggest if project uses uv (has uv.lock file)
        if not Path("uv.lock").exists():
            return

        # Don't prompt if already configured
        if self._alias_exists():
            return

        # Don't prompt if we've asked before
        if self.MARKER_FILE.exists():
            return

        # Don't prompt for certain commands
        if "--help" in sys.argv or "-h" in sys.argv:
            return

        # Mark that we've asked (do this first so we don't ask again even if they Ctrl+C)
        self.MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.MARKER_FILE.touch()

        click.echo()
        click.secho("💡 Tip: ", fg="yellow", bold=True, nl=False)
        click.echo(
            f"Set up `{self.ALIAS_NAME}` as an alias to run commands faster (e.g., `{self.ALIAS_NAME} dev` instead of `uv run plain dev`)."
        )
        click.echo()

        # Check if shell is supported
        if not self.shell or not self.shell_config_file:
            click.echo("To set this up manually, add to your shell config:")
            click.echo(f'  alias {self.ALIAS_NAME}="{self.ALIAS_COMMAND}"')
            click.echo()
            return

        # Offer to set it up
        prompt_text = f"Would you like to add this to {self.shell_config_file.name}?"
        if click.confirm(prompt_text, default=False):
            click.echo()
            if self._add_alias_to_shell():
                sys.exit(0)  # Completely exit

        click.echo()
