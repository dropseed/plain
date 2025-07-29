# CLI

**The `plain` CLI and how to add your own commands to it.**

- [Overview](#overview)
- [Adding commands](#adding-commands)

## Overview

Commands are written using [Click](https://click.palletsprojects.com/en/8.1.x/)
(one of Plain's few dependencies),
which has been one of those most popular CLI frameworks in Python for a long time.

## Adding commands

The [`register_cli`](./registry.py#register_cli) decorator can be used to add your own commands to the `plain` CLI.

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
