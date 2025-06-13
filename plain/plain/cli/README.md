# CLI

**The `plain` CLI and how to add your own commands to it.**

Commands are written using [Click](https://click.palletsprojects.com/en/8.1.x/)
(one of Plain's few dependencies),
which has been one of those most popular CLI frameworks in Python for a long time.

## Built-in commands

### `plain build`

Compile static assets (used in the deploy/production process).

Automatically runs `plain tailwind build` if [plain.tailwind](/plain-tailwind/) is installed.

### `plain create`

Create a new local package.

### `plain preflight`

Run preflight checks to ensure your app is ready to run.

### `plain run`

Run a Python script in the context of your app.

### `plain setting`

View the runtime value of a named setting.

### `plain help`

Print help for all available commands and subcommands.
Each command's help output is prefixed with the full command name for
readability.

### `plain shell`

Open a Python shell with the Plain loaded.

To auto-load models or run other code at shell launch,
create an `app/shell.py` and it will be imported automatically.

```python
# app/shell.py
from app.organizations.models import Organization

__all__ = [
    "Organization",
]
```

### `plain urls list`

List all the URL patterns in your app.

### `plain utils generate-secret-key`

Generate a new secret key for your app, to be used in `settings.SECRET_KEY`.

## Adding commands

The `register_cli` decorator can be used to add your own commands to the `plain` CLI.

```python
import click
from plain.cli import register_cli


@register_cli("example-subgroup-name")
@click.group()
def cli():
    """Custom example commands"""
    pass

@cli.command()
def example_command():
    click.echo("An example command!")
```

Then you can run the command with `plain`.

```bash
$ plain example-subgroup-name example-command
An example command!
```

Technically you can register a CLI from anywhere, but typically you will do it in either `app/cli.py` or a package's `<pkg>/cli.py`, as those modules will be autoloaded by Plain.
