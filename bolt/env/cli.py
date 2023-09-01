import os

import click

from bolt.exceptions import ValidationError

from .encrypt import Env


@click.group("env")
def cli():
    """Manage .env files"""
    pass


@cli.command()
@click.argument("files", nargs=-1)
def check(files):
    """Check .env files for errors and out-of-sync diffs"""

    if not files:
        # Get all .env files in the current directory by default
        files = Env.find_files(os.getcwd())

    has_diffs = False

    for file in files:
        # Convert to relative path for readability
        file = os.path.relpath(file, os.getcwd())

        click.secho(file, bold=True)

        env = Env(file)

        try:
            env.check()
        except ValidationError as e:
            click.secho(str(e.message), fg="red")
            exit(1)

        if diff_str := env.diff():
            print(diff_str)
            has_diffs = True
        else:
            print("No changes")

        print()

    if has_diffs:
        exit(1)


@cli.command()
@click.argument("files", nargs=-1)
@click.option("--force", is_flag=True, help="Overwrite existing .encrypted files")
@click.option("--diff", is_flag=True, help="Show diff of encrypted file")
def encrypt(files, force, diff):
    """Encrypt .env files so they can be stored in git"""

    if not files:
        # Get all .env files in the current directory by default
        files = Env.find_files(os.getcwd())

    for file in files:
        # Convert to relative path for readability
        file = os.path.relpath(file, os.getcwd())

        click.secho(file, bold=True)

        env = Env(file)

        try:
            env.check()
        except ValidationError as e:
            click.secho(str(e.message), fg="red")
            exit(1)

        if env.encrypted_file.exists():
            if diff:
                if diff_str := env.diff():
                    print(diff_str)
                else:
                    print("No changes")
            elif not force:
                click.secho(
                    f'"{env.encrypted_file}" already exists, skipping (use --force to overwrite or --diff to see changes)',
                    fg="yellow",
                )

        if force or not env.encrypted_file.exists():
            env.encrypt()
            click.secho(f"Encrypted to {env.encrypted_file.path}", fg="green")

        print()


@cli.command()
@click.argument("files", nargs=-1)
@click.option("--force", is_flag=True, help="Overwrite existing .env files")
@click.option("--diff", is_flag=True, help="Show diff of decrypted file")
def decrypt(files, force, diff):
    """Decrypt .env files so they can be used locally"""

    if not files:
        # Get all .env files in the current directory by default
        files = Env.find_files(os.getcwd())

    for file in files:
        # Convert to relative path for readability
        file = os.path.relpath(file, os.getcwd())

        click.secho(file, bold=True)

        env = Env(file)

        try:
            env.check()
        except ValidationError as e:
            click.secho(str(e.message), fg="red")
            exit(1)

        if env.env_file.exists():
            if diff:
                if diff_str := env.diff():
                    print(diff_str)
                else:
                    print("No changes")
            elif not force:
                click.secho(
                    f'"{env.env_file}" already exists, skipping (use --force to overwrite or --diff to see changes)',
                    fg="yellow",
                )

        if force or not env.env_file.exists():
            env.decrypt()
            click.secho(f"Decrypted to {env.env_file.path}", fg="green")

        print()
