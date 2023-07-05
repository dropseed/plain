import difflib
import os

import click
from cryptography.fernet import Fernet


@click.group("env")
def cli():
    """Manage .env files"""
    pass


@cli.command()
@click.argument("files", nargs=-1)
@click.option("--key", help="Encryption key", envvar="BOLT_ENV_ENCRYPTION_KEY")
@click.option("--force", is_flag=True, help="Overwrite existing .encrypted files")
def encrypt(files, key, force, diff):
    """Encrypt .env files so they can be stored in git"""

    if not files:
        # Get all .env files in the current directory by default
        files = [
            x
            for x in os.listdir()
            if x.startswith(".env")
            and not x.endswith(".encrypted")
            and x != ".env.example"
        ]

    for file in files:
        if not os.path.exists(file):
            print(f'File "{file}" does not exist')
            exit(1)

        basename = os.path.basename(file)

        if not basename.startswith(".env"):
            print("This command should only be used on .env files")
            exit(1)

        if basename == ".env.example":
            print("This command should not be used on .env.example files")
            exit(1)

    if not key:
        for f in os.listdir():
            if os.path.basename(f).startswith(".env") and f.endswith(".encrypted"):
                print("No encryption key provided, but .encrypted files already exist")
                exit(1)

        key = Fernet.generate_key()
        print("Generated encryption key:", click.style(key, fg="green", bold=True))
        print("You should save this somewhere safe, like a password manager!")

    fernet = Fernet(key)

    for file in files:
        print("Encrypting", file)
        with open(file, "rb") as f:
            data = f.read()

        encrypted_data = fernet.encrypt(data)
        encrypted_path = file + ".encrypted"

        if os.path.exists(encrypted_path) and not force:
            print(
                f'File "{encrypted_path}" already exists, skipping (use --force to overwrite or --diff to see changes)'
            )
            continue

        with open(encrypted_path, "wb") as f:
            f.write(encrypted_data)


@cli.command()
@click.argument("files", nargs=-1)
@click.option("--key", help="Encryption key", envvar="BOLT_ENV_ENCRYPTION_KEY")
@click.option("--force", is_flag=True, help="Overwrite existing .env files")
def decrypt(files, key, force, diff):
    """Decrypt .env files so they can be used locally"""

    if not files:
        files = [".env.encrypted"]

    for file in files:
        if not os.path.exists(file):
            print(f'File "{file}" does not exist')
            exit(1)
        basename = os.path.basename(file)
        if not basename.startswith(".env"):
            print("This command should only be used on .env files")
            exit(1)
        elif not basename.endswith(".encrypted"):
            print("This command should only be used on .env.encrypted files")
            exit(1)

    if not key:
        click.secho(
            "No encryption key provided. Use --key or BOLT_ENV_ENCRYPTION_KEY.",
            fg="red",
            bold=True,
        )
        exit(1)

    fernet = Fernet(key)

    for file in files:
        with open(file, "rb") as f:
            encrypted_data = f.read()

        data = fernet.decrypt(encrypted_data)

        decrypted_path = file.replace(".encrypted", "")

        if os.path.exists(decrypted_path) and not force:
            print(
                f'File "{decrypted_path}" already exists, skipping (use --force to overwrite or --diff to see changes)'
            )
            continue

        with open(decrypted_path, "wb") as f:
            f.write(data)


@cli.command()
@click.argument("files", nargs=-1)
@click.option("--key", help="Encryption key", envvar="BOLT_ENV_ENCRYPTION_KEY")
def check(files, key):
    if not files:
        files = [x for x in os.listdir() if x.startswith(".env") and x.endswith(".encrypted")]

    if not key:
        click.secho(
            "No encryption key provided. Use --key or BOLT_ENV_ENCRYPTION_KEY.",
            fg="red",
            bold=True,
        )
        exit(1)

    fernet = Fernet(key)

    differs = False

    for file in files:
        decrypted_path = file.replace(".encrypted", "")

        click.secho(f"Checking {file}->{decrypted_path} ", bold=True, nl=False)

        with open(file, "rb") as f:
            encrypted_data = f.read()

        data = fernet.decrypt(encrypted_data)

        if os.path.exists(decrypted_path):
            with open(decrypted_path, "rb") as f:
                old_data = f.read()

            diff = difflib.unified_diff(
                old_data.decode().splitlines(),
                data.decode().splitlines(),
                fromfile=decrypted_path,
                tofile=file,
            )
            diff_str = "\n".join(diff)
            if diff_str:
                click.secho("Changes found", fg="yellow")
                print(diff_str)
                differs = True
            else:
                click.secho("No changes", fg="green")
        else:
            print("Not decrypted yet")

    if differs:
        click.secho("\nUse `bolt env encrypt` to save your changes, or `bolt env decrypt` to discard them", fg="yellow")
        exit(1)
