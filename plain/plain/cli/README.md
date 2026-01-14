# plain.cli

**The `plain` command-line interface and tools for adding custom commands.**

- [Overview](#overview)
- [Adding commands](#adding-commands)
    - [Register a command group](#register-a-command-group)
    - [Register a shortcut command](#register-a-shortcut-command)
    - [Mark commands as common](#mark-commands-as-common)
- [Shell](#shell)
    - [Run a script with app context](#run-a-script-with-app-context)
    - [SHELL_IMPORT](#shell_import)
- [Built-in commands](#built-in-commands)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The `plain` CLI provides commands for running your app, managing databases, starting shells, and more. You can also add your own commands using the [`register_cli`](./registry.py#register_cli) decorator.

Commands are written using [Click](https://click.palletsprojects.com/), a popular Python CLI framework that is one of Plain's few dependencies.

```python
import click
from plain.cli import register_cli


@register_cli("hello")
@click.command()
def cli():
    """Say hello"""
    click.echo("Hello from my custom command!")
```

After defining this command, you can run it with `plain hello`:

```bash
$ plain hello
Hello from my custom command!
```

## Adding commands

You can register commands from anywhere, but Plain will automatically import `cli.py` modules from your app and installed packages. The most common locations are:

- `app/cli.py` for app-specific commands
- `<package>/cli.py` for package-specific commands

### Register a command group

Use [`@register_cli`](./registry.py#register_cli) with a Click group to create subcommands:

```python
@register_cli("users")
@click.group()
def cli():
    """User management commands"""
    pass


@cli.command()
@click.argument("email")
def create(email):
    """Create a new user"""
    click.echo(f"Creating user: {email}")


@cli.command()
def list():
    """List all users"""
    click.echo("Listing users...")
```

This creates `plain users create` and `plain users list` commands.

### Register a shortcut command

Some commands are used frequently enough to warrant a top-level shortcut. You can indicate that a command is a shortcut for a subcommand by passing `shortcut_for`:

```python
@register_cli("migrate", shortcut_for="models")
@click.command()
def migrate():
    """Run database migrations"""
    # ...
```

This makes `plain migrate` available as a shortcut for `plain models migrate`. The shortcut relationship is shown in help output.

### Mark commands as common

Use the [`common_command`](./runtime.py#common_command) decorator to highlight frequently used commands in help output:

```python
from plain.cli import register_cli
from plain.cli.runtime import common_command


@register_cli("dev")
@common_command
@click.command()
def dev():
    """Start development server"""
    # ...
```

Common commands appear in a separate "Common Commands" section when running `plain --help`.

## Shell

The `plain shell` command starts an interactive Python shell with your Plain app already loaded.

```bash
$ plain shell
```

If you have IPython installed, it will be used automatically. You can also specify an interface explicitly:

```bash
$ plain shell --interface ipython
$ plain shell --interface bpython
$ plain shell --interface python
```

For one-off commands, use the `-c` flag:

```bash
$ plain shell -c "from app.users.models import User; print(User.query.count())"
```

### Run a script with app context

The `plain run` command executes a Python script with your app context already set up:

```bash
$ plain run scripts/import_data.py
```

This is useful for one-off scripts that need access to your models and settings.

### SHELL_IMPORT

Customize what gets imported automatically when the shell starts by setting `SHELL_IMPORT` in your settings:

```python
# app/settings.py
SHELL_IMPORT = "app.shell"
```

Then create that module with the objects you want available:

```python
# app/shell.py
from app.projects.models import Project
from app.users.models import User

__all__ = ["Project", "User"]
```

Now when you run `plain shell`, those objects will be automatically imported and available.

## Built-in commands

Plain includes several built-in commands:

| Command               | Description                              |
| --------------------- | ---------------------------------------- |
| `plain shell`         | Interactive Python shell                 |
| `plain run <script>`  | Execute a Python script with app context |
| `plain server`        | Production-ready WSGI server             |
| `plain preflight`     | Validation checks before deployment      |
| `plain create <name>` | Create a new local package               |
| `plain settings`      | View current settings                    |
| `plain urls`          | List all URL patterns                    |
| `plain docs`          | View package documentation               |
| `plain build`         | Run build commands                       |
| `plain install`       | Install package dependencies             |
| `plain upgrade`       | Upgrade Plain packages                   |

Additional commands are added by installed packages (like `plain models migrate` from plain.models).

## FAQs

#### How do I run commands that don't need the app to be set up?

Use the [`without_runtime_setup`](./runtime.py#without_runtime_setup) decorator for commands that don't need access to settings or app code. This is useful for commands that fork processes (like `server`) where setup should happen in the worker process:

```python
from plain.cli.runtime import without_runtime_setup


@without_runtime_setup
@click.command()
def server():
    """Start the server"""
    # Setup happens in the worker process, not here
    # ...
```

#### Where should I put my custom commands?

Put app-specific commands in `app/cli.py`. Plain will automatically import this module. If you're building a reusable package, put commands in `<package>/cli.py`.

#### Can I use argparse instead of Click?

No, Plain's CLI is built on Click and the registration system expects Click commands. However, Click is well-documented and provides a better developer experience than argparse for most use cases.

## Installation

The CLI is included with Plain. No additional installation is required.
