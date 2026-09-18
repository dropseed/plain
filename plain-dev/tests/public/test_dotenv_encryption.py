import importlib.metadata
import os
from pathlib import Path

import plain.runtime
import pytest
from click.testing import CliRunner
from plain.cli.core import cli as plain_cli
from plain.dev.dotenv import (
    Binding,
    decrypt_env_value,
    encrypt_env_value,
    find_env_binding,
    generate_env_key,
    is_encrypted_value,
    load_dotenv,
    load_dotenv_files,
    parse_dotenv,
)
from plain.dev.env import cli as env_cli
from plain.exceptions import ImproperlyConfigured


@pytest.fixture
def env_key():
    return generate_env_key()


@pytest.fixture
def runner():
    return CliRunner()


# --- crypto helpers ---


def test_encrypt_decrypt_roundtrip(env_key):
    encrypted = encrypt_env_value("hunter2", env_key)
    assert encrypted.startswith("encrypted:")
    assert is_encrypted_value(encrypted)
    assert decrypt_env_value(encrypted, env_key) == "hunter2"


def test_encrypt_decrypt_roundtrip_multiline(env_key):
    pem = "-----BEGIN PRIVATE KEY-----\nabc\ndef\n-----END PRIVATE KEY-----\n"
    encrypted = encrypt_env_value(pem, env_key)
    assert "\n" not in encrypted
    assert decrypt_env_value(encrypted, env_key) == pem


def test_is_encrypted_value_is_a_prefix_test(env_key):
    """The tag is syntax, not a token shape — anything starting with it is encrypted."""
    assert is_encrypted_value(encrypt_env_value("x", env_key))
    assert is_encrypted_value("encrypted:not-a-real-token")
    assert not is_encrypted_value("see encrypted:gAAAA")
    assert not is_encrypted_value("plain")


# --- loader ---


def test_loader_decrypts_with_key_in_environ(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_key_from_env_local_decrypts_env_dev(write, monkeypatch, env_key):
    """`.env.local` loads before `.env.dev`; its key line is what decrypts `.env.dev`."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.local", f"DEV_ENV_KEY={env_key}\n")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_key_after_values_in_same_file(write, monkeypatch, env_key):
    """Decryption happens after the whole file parses, so order within a file doesn't matter."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(
        ".env.dev",
        f"SECRET={encrypt_env_value('s3cret', env_key)}\nDEV_ENV_KEY={env_key}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_key_from_command_substitution(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.local", f"DEV_ENV_KEY=$(echo {env_key})\n")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["DEV_ENV_KEY"] == env_key
    assert os.environ["SECRET"] == "s3cret"


def test_missing_key_raises_naming_variable_and_file(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "SECRET" in message
    assert ".env.dev" in message
    assert "DEV_ENV_KEY" in message
    assert ".env.dev.local" in message
    assert "SECRET" not in os.environ


def test_missing_key_hint_without_plain_env_names_env_local(write, env_key):
    write(".env", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    assert ".env.local" in str(excinfo.value)
    assert ".env.dev.local" not in str(excinfo.value)


def test_empty_key_blames_the_command_that_should_have_produced_it(
    write, monkeypatch, env_key
):
    """An empty DEV_ENV_KEY means its `$(...)` lookup failed, not that it's unset."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", "")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "empty value" in message
    assert "op read" in message
    assert "is not set" not in message


def test_wrong_key_raises(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", generate_env_key())
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "SECRET" in message
    assert ".env.dev" in message
    assert "does not decrypt" in message
    assert "SECRET" not in os.environ


def test_existing_environ_value_is_left_alone(write, monkeypatch, env_key):
    """A key already in os.environ wins; its encrypted line is never decrypted (no key needed)."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("SECRET", "from-shell")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "from-shell"


def test_bound_key_with_multiline_duplicate_in_later_file(write, monkeypatch, env_key):
    """A lower-precedence multi-line duplicate is skipped whole — its inner lines aren't bindings."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.local", "SECRET=from-local\n")
    write(".env.dev", 'SECRET="l1\nFOO=bar\nl3"\nAFTER=1\n')
    load_dotenv_files()
    assert os.environ["SECRET"] == "from-local"
    assert "FOO" not in os.environ
    assert os.environ["AFTER"] == "1"


def test_bound_key_never_runs_its_commands(write, monkeypatch):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("SECRET", "from-shell")
    write(
        ".env.dev", 'SECRET=$(touch marker-unquoted)\nSECRET="$(touch marker-quoted)"\n'
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "from-shell"
    assert not Path("marker-unquoted").exists()
    assert not Path("marker-quoted").exists()


def test_encrypted_value_in_earlier_file_beats_plain_value_in_later_file(
    write, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.local", f"SECRET={encrypt_env_value('from-local', env_key)}\n")
    write(".env.dev", "SECRET=from-dev\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "from-local"


def test_decrypted_plaintext_is_bound_literally(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    plaintext = "cost is $HOME and $(echo x) and ${HOME}"
    write(".env.dev", f"SECRET={encrypt_env_value(plaintext, env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == plaintext


# --- the `encrypted:` tag is syntax ---


def test_encrypted_prefix_inside_longer_value_is_plain_text(
    write, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    encrypted = encrypt_env_value("s3cret", env_key)
    write(".env.dev", f"NOTE=see {encrypted}\n")
    load_dotenv_files()  # no key needed, nothing to decrypt
    assert os.environ["NOTE"] == f"see {encrypted}"


def test_quoted_encrypted_prefix_is_plain_text(write, monkeypatch):
    """Quoting is the escape hatch for a literal value that starts with the tag."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.dev", "SINGLE='encrypted:aes'\nDOUBLE=\"encrypted:aes\"\n")
    load_dotenv_files()  # no key needed
    assert os.environ["SINGLE"] == "encrypted:aes"
    assert os.environ["DOUBLE"] == "encrypted:aes"


def test_unquoted_malformed_encrypted_value_raises_with_quoting_hint(
    write, monkeypatch, env_key
):
    """An unquoted `encrypted:` value that doesn't decrypt is a mistake, not plain text."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", "MODE=encrypted:aes\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "MODE" in message
    assert ".env.dev" in message
    assert "quote it" in message
    assert "MODE" not in os.environ


# --- references to encrypted values ---


def test_reference_to_encrypted_value_in_same_file_raises(write, monkeypatch, env_key):
    """`B=$A` where A is encrypted used to expand to A's ciphertext."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(
        ".env.dev",
        f"SECRET={encrypt_env_value('s3cret', env_key)}\nURL=https://$SECRET@example.com\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "URL in .env.dev references SECRET" in message
    assert "can't be referenced from other values" in message
    assert "URL" not in os.environ


def test_reference_to_encrypted_value_in_earlier_file_raises(
    write, monkeypatch, env_key
):
    """Across files it used to expand to an empty string."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.local", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    write(".env.dev", "URL=${SECRET}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    assert "URL in .env.dev references SECRET" in str(excinfo.value)


def test_reference_to_a_shadowed_encrypted_value_uses_the_bound_value(
    write, monkeypatch, env_key
):
    """A shadowed encrypted line isn't the value of the name, so referencing it is fine."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("SECRET", "from-shell")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nURL=$SECRET\n")
    load_dotenv_files()  # no key needed
    assert os.environ["URL"] == "from-shell"


# --- one parser ---


def test_digit_leading_key_is_skipped_by_loader_and_find_env_binding(
    write, monkeypatch
):
    """`find_env_binding` is the loader's parser in raw mode, so they agree on what's a binding."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    content = "1BAD=x\nGOOD=y\n"
    write(".env.dev", content)
    load_dotenv_files()
    assert "1BAD" not in os.environ
    assert os.environ["GOOD"] == "y"

    assert find_env_binding(content, "1BAD") is None
    assert find_env_binding(content, "GOOD") is not None


def test_find_env_binding_does_not_expand_or_execute():
    content = 'A=$(touch marker)\nB="$HOME/x"\nC=encrypted:abc\n'
    command = find_env_binding(content, "A")
    assert command == Binding(
        key="A",
        value="$(touch marker)",
        encrypted=False,
        source=None,
        key_start=0,
        value_end=17,
    )
    assert not Path("marker").exists()

    quoted = find_env_binding(content, "B")
    assert quoted is not None
    assert quoted.value == "$HOME/x"

    encrypted = find_env_binding(content, "C")
    assert encrypted is not None
    assert encrypted.encrypted is True


# --- single-file helpers ---


def test_load_dotenv_decrypts_single_file(write, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write("custom.env", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    assert load_dotenv("custom.env") is True
    assert os.environ["SECRET"] == "s3cret"


def test_load_dotenv_without_decrypt_leaves_encrypted_values_unbound(write, env_key):
    write("custom.env", f"PLAIN=x\nSECRET={encrypt_env_value('s3cret', env_key)}\n")
    assert load_dotenv("custom.env", decrypt=False) is True
    assert os.environ["PLAIN"] == "x"
    assert "SECRET" not in os.environ


def test_parse_dotenv_decrypts(write, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nPLAIN=x\n")
    assert parse_dotenv(".env.dev") == {"SECRET": "s3cret", "PLAIN": "x"}
    assert "SECRET" not in os.environ


def test_parse_dotenv_uses_the_key_line_in_the_same_file(write, env_key):
    write(
        ".env.dev",
        f"DEV_ENV_KEY={env_key}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    assert parse_dotenv(".env.dev")["SECRET"] == "s3cret"
    assert "DEV_ENV_KEY" not in os.environ


def test_parse_dotenv_without_key_raises(write, env_key):
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        parse_dotenv(".env.dev")
    assert "SECRET" in str(excinfo.value)


# --- plain env CLI ---


def test_plain_env_is_registered_as_a_cli_entry_point():
    """plain.dev contributes `plain env` through the `plain.cli` entry point group."""
    entry_points = importlib.metadata.entry_points(group="plain.cli")
    assert entry_points["env"].load() is env_cli


def test_plain_env_runs_without_runtime_setup(monkeypatch):
    """`plain env` is the command you run when loading the app would fail."""
    setup_calls = []
    monkeypatch.setattr(plain.runtime, "setup", lambda: setup_calls.append("setup"))

    result = CliRunner().invoke(plain_cli, ["env", "--help"], prog_name="plain")

    assert result.exit_code == 0, result.output
    assert "set" in result.output
    assert setup_calls == []


def test_env_key_prints_a_fernet_key(runner):
    from cryptography.fernet import Fernet

    result = runner.invoke(env_cli, ["key"])
    assert result.exit_code == 0, result.output
    key = result.stdout.strip()
    assert len(key) == 44
    Fernet(key.encode())


def test_env_key_works_on_a_clone_with_no_key(write, runner, env_key):
    """`plain env key` is the fix for a missing key, so it can't need one itself."""
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    result = runner.invoke(env_cli, ["key"])
    assert result.exit_code == 0, result.output
    assert len(result.stdout.strip()) == 44
    assert "SECRET" not in os.environ


def test_env_set_rotates_values_encrypted_with_an_older_key(
    write, runner, monkeypatch, env_key
):
    """Existing values are never validated against the key, so a new key can be used."""
    write(".env.dev", f"SECRET={encrypt_env_value('old', env_key)}\n")
    monkeypatch.setenv("DEV_ENV_KEY", generate_env_key())
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output
    assert parse_dotenv(".env.dev") == {"SECRET": "new"}


def test_env_set_appends_new_line(
    write, runner, monkeypatch, env_key, reload_dotenv_files
):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", "FIRST=1\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code == 0, result.output
    assert "s3cret" not in result.output

    content = Path(".env.dev").read_text()
    assert content.startswith("FIRST=1\nSECRET=encrypted:")
    assert content.endswith("\n")
    monkeypatch.setenv("PLAIN_ENV", "dev")
    reload_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_env_set_replaces_single_line_value(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", "A=1\nexport SECRET = old # keep me\nB=2\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output

    lines = Path(".env.dev").read_text().splitlines()
    assert lines[0] == "A=1"
    assert lines[1].startswith("export SECRET=encrypted:")
    assert lines[1].endswith(" # keep me")
    assert lines[2] == "B=2"
    assert len(lines) == 3


def test_env_set_replaces_multiline_double_quoted_value(
    write, runner, monkeypatch, env_key
):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    before = "# header\nA=1\n"
    after = "\n\nB='multi\nline'\n"
    write(
        ".env.dev",
        before + 'SECRET="line one\nline \\"two\\"\nline three"' + after,
    )
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output

    content = Path(".env.dev").read_text()
    assert content.startswith(before + "SECRET=encrypted:")
    assert content.endswith(after)
    assert content.count("SECRET=") == 1
    assert "line one" not in content
    assert parse_dotenv(".env.dev") == {"A": "1", "SECRET": "new", "B": "multi\nline"}


def test_env_set_preserves_crlf_line_endings(runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    Path(".env.dev").write_bytes(b"A=1\r\nSECRET=old\r\nB=2\r\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output

    raw = Path(".env.dev").read_bytes()
    assert raw.startswith(b"A=1\r\nSECRET=encrypted:")
    assert raw.endswith(b"\r\nB=2\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")

    result = runner.invoke(env_cli, ["set", "NEW", "x"])
    assert result.exit_code == 0, result.output
    raw = Path(".env.dev").read_bytes()
    assert raw.endswith(b"\r\n")
    assert b"\r\nNEW=encrypted:" in raw


def test_env_set_replaces_second_binding_on_a_line(write, runner, monkeypatch, env_key):
    """`A="x" SECRET=old` binds both in the loader, so `set` must find SECRET there too."""
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", 'A="x" SECRET=old\n')
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output
    content = Path(".env.dev").read_text()
    assert content.startswith('A="x" SECRET=encrypted:')
    assert content.count("SECRET=") == 1
    assert parse_dotenv(".env.dev") == {"A": "x", "SECRET": "new"}


def test_env_set_fails_with_malformed_key(runner, monkeypatch):
    monkeypatch.setenv("DEV_ENV_KEY", "not-a-key")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code != 0
    assert "not a valid key" in result.output
    assert not Path(".env.dev").exists()


def test_env_set_fails_with_empty_key(runner, monkeypatch):
    monkeypatch.setenv("DEV_ENV_KEY", "")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code != 0
    assert "empty value" in result.output
    assert "op read" in result.output
    assert not Path(".env.dev").exists()


def test_env_set_refuses_to_wait_on_a_tty(runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    monkeypatch.setattr("plain.dev.env._stdin_is_a_tty", lambda: True)
    result = runner.invoke(env_cli, ["set", "SECRET"])
    assert result.exit_code != 0
    assert "Pass VALUE" in result.output
    assert not Path(".env.dev").exists()


def test_env_set_reads_value_from_stdin(runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    pem = "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
    result = runner.invoke(env_cli, ["set", "PEM"], input=pem)
    assert result.exit_code == 0, result.output
    # Exactly one trailing newline is stripped
    assert parse_dotenv(".env.dev") == {"PEM": pem.removesuffix("\n")}


def test_env_set_reports_binary_stdin_as_a_value_problem(runner, monkeypatch, env_key):
    """A key that works must not be blamed for a value that isn't text."""
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    result = runner.invoke(env_cli, ["set", "BLOB"], input=b"\xff\xfe\x00")
    assert result.exit_code != 0
    assert "not valid UTF-8" in result.output
    assert "not a valid key" not in result.output
    assert not Path(".env.dev").exists()


def test_env_set_creates_file(runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret", "-f", ".env.other"])
    assert result.exit_code == 0, result.output
    assert Path(".env.other").read_text().startswith("SECRET=encrypted:")
    assert not Path(".env.dev").exists()


def test_env_set_fails_without_key(runner):
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code != 0
    assert "DEV_ENV_KEY is not set" in result.output
    assert not Path(".env.dev").exists()


def test_env_set_warns_when_a_higher_precedence_file_wins(
    write, runner, monkeypatch, env_key
):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.local", "SECRET=from-local\n")
    write(".env.dev", "A=1\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code == 0, result.output
    assert "SECRET is also set in .env.local" in result.stderr
    assert "outranks .env.dev" in result.stderr


def test_env_set_warns_when_the_shell_wins(runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    monkeypatch.setenv("SECRET", "from-shell")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code == 0, result.output
    assert "SECRET is also set in your shell environment" in result.stderr


def test_env_set_does_not_warn_when_replacing_its_own_file(
    write, runner, monkeypatch, env_key
):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", "SECRET=old\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output
    assert "outranks" not in result.stderr


def test_env_get_decrypts(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(
        ".env.dev", f"OTHER=$(exit 1)\nSECRET={encrypt_env_value('s3cret', env_key)}\n"
    )
    result = runner.invoke(env_cli, ["get", "SECRET"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "s3cret\n"


def test_env_get_reports_plaintext_binding(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", env_key)
    write(".env.dev", 'SECRET="not encrypted"\n')
    result = runner.invoke(env_cli, ["get", "SECRET"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "not encrypted\n"
    assert "not encrypted (printing it as written)" in result.stderr


def test_env_get_wrong_key_fails_clearly(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("DEV_ENV_KEY", generate_env_key())
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    result = runner.invoke(env_cli, ["get", "SECRET"])
    assert result.exit_code != 0
    assert "does not decrypt SECRET" in result.output


def test_env_get_from_a_file_under_another_key(write, runner, monkeypatch, env_key):
    """`-f` reads a file the loaded ladder can't decrypt, which is the point of `-f`."""
    other_key = generate_env_key()
    write(".env.dev", f"SECRET={encrypt_env_value('dev', env_key)}\n")
    write(".env.other", f"SECRET={encrypt_env_value('other', other_key)}\n")
    monkeypatch.setenv("DEV_ENV_KEY", other_key)
    result = runner.invoke(env_cli, ["get", "SECRET", "-f", ".env.other"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "other\n"


def test_env_get_restores_escaped_dollar_in_double_quoted_plaintext(runner, write):
    write(".env.dev", 'PRICE="cost is \\$5"\n')
    result = runner.invoke(env_cli, ["get", "PRICE"])
    assert result.exit_code == 0, result.output
    assert result.output.strip().splitlines()[-1] == "cost is $5"


def test_env_reports_a_broken_env_file_without_a_traceback(write, runner, env_key):
    """`plain env` runs without app setup, so it renders loader errors itself."""
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nURL=$SECRET\n")
    result = runner.invoke(env_cli, ["key"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "URL in .env.dev references SECRET" in result.output
