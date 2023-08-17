
## CLI - click

A good CLI is an important part of any framework.
It has always bugged me that you have to do things like `python manage.py <cmd>` to run commands in Django.

Why not `django <cmd>`? In Bolt, you can simply run `bolt <cmd>`.

TL;DR

```python
# Create cli.py in your app
```

### Removed manage.py

I haven't used `manage.py` as a customization point in a long time.
And when I did,
it was the wrong place to do it.

### Click

I have mixed feelings on this,
but [Click](https://click.palletsprojects.com/en/8.1.x/) has always been a great option for building CLIs in Python.

In some ways it feels silly to use a third-party package just for this,
but I have *never* enjoyed working with Python's built-in `argparse` module.

```python
# myapp/cli.py
import click

@click.command()
@click.option("--name", default="World")
def cli(name):
    click.echo(f"Hello {name}!")
```

I looked at using [Fire](https://github.com/google/python-fire) for this instead.
I think something like that has some cool tradeoffs,
but the end-user CLI experience just wasn't good enough as-is.

### Entry-points (instead of bin search)
