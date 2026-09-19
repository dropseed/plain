import importlib.metadata
import os
from pathlib import Path

import plain.runtime
import pytest
from click.testing import CliRunner
from cryptography.fernet import InvalidToken
from plain.cli.core import cli as plain_cli
from plain.dev.dotenv import (
    Binding,
    decrypt_env_value,
    encrypt_env_value,
    find_env_binding,
    is_encrypted_value,
    load_dotenv,
    load_dotenv_files,
    parse_dotenv,
)
from plain.dev.env import cli as env_cli
from plain.dev.envkeys import (
    env_key_id,
    generate_env_key,
    is_valid_env_key,
    store_env_key,
    stored_env_key_path,
)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_key_from_env_local_decrypts_env_dev(write, monkeypatch, env_key):
    """`.env.local` loads before `.env.dev`; its key line is what decrypts `.env.dev`."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.local", f"PLAIN_ENV_KEY={env_key}\n")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_key_after_values_in_same_file(write, monkeypatch, env_key):
    """Decryption happens after the whole file parses, so order within a file doesn't matter."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(
        ".env.dev",
        f"SECRET={encrypt_env_value('s3cret', env_key)}\nPLAIN_ENV_KEY={env_key}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_missing_key_raises_naming_variable_and_file(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "SECRET" in message
    assert ".env.dev" in message
    assert "PLAIN_ENV_KEY" in message
    assert "plain env init" in message
    assert "plain env unlock" in message
    assert "SECRET" not in os.environ


def test_empty_key_is_reported_as_empty(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", "")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "empty value" in message
    assert "is not set" not in message


def test_wrong_key_raises(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", generate_env_key())
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


def test_bound_key_keeps_the_value_from_the_shell(write, monkeypatch):
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.local", f"SECRET={encrypt_env_value('from-local', env_key)}\n")
    write(".env.dev", "SECRET=from-dev\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "from-local"


def test_decrypted_plaintext_is_bound_literally(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write("custom.env", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    assert load_dotenv("custom.env") is True
    assert os.environ["SECRET"] == "s3cret"


def test_load_dotenv_without_decrypt_leaves_encrypted_values_unbound(write, env_key):
    write("custom.env", f"PLAIN=x\nSECRET={encrypt_env_value('s3cret', env_key)}\n")
    assert load_dotenv("custom.env", decrypt=False) is True
    assert os.environ["PLAIN"] == "x"
    assert "SECRET" not in os.environ


def test_parse_dotenv_decrypts(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nPLAIN=x\n")
    assert parse_dotenv(".env.dev") == {"SECRET": "s3cret", "PLAIN": "x"}
    assert "SECRET" not in os.environ


def test_parse_dotenv_uses_the_key_line_in_the_same_file(write, env_key):
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY={env_key}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    assert parse_dotenv(".env.dev")["SECRET"] == "s3cret"
    assert "PLAIN_ENV_KEY" not in os.environ


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


def test_plain_env_runs_without_runtime_setup(runner, monkeypatch):
    """`plain env` is the command you run when loading the app would fail."""
    setup_calls = []
    monkeypatch.setattr(plain.runtime, "setup", lambda: setup_calls.append("setup"))

    result = runner.invoke(plain_cli, ["env", "--help"], prog_name="plain")

    assert result.exit_code == 0, result.output
    assert "set" in result.output
    assert setup_calls == []


def test_env_init_stores_the_key_and_names_it_in_the_file(runner, isolated_env_keys):
    result = runner.invoke(env_cli, ["init"])
    assert result.exit_code == 0, result.output

    binding = find_env_binding(Path(".env.dev").read_text(), "PLAIN_ENV_KEY_ID")
    assert binding is not None
    key_id = binding.value
    assert len(key_id) == 12

    stored = stored_env_key_path(key_id)
    assert stored.parent == isolated_env_keys
    assert os.stat(stored).st_mode & 0o777 == 0o600
    key = stored.read_text().strip()
    assert is_valid_env_key(key)
    assert env_key_id(key) == key_id
    # The key itself is never printed.
    assert key not in result.output


def test_env_init_refuses_a_file_that_already_names_a_key(write, runner, env_key):
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    result = runner.invoke(env_cli, ["init"])
    assert result.exit_code != 0
    assert "already names key" in result.output
    assert "plain env unlock" in result.output


def test_env_set_uses_the_key_the_file_names(write, runner, env_key):
    """`-f` targets a file under another key; that file's own id decides."""
    other_key = generate_env_key()
    store_env_key(env_key)
    store_env_key(other_key)
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    write(".env.other", f"PLAIN_ENV_KEY_ID={env_key_id(other_key)}\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret", "-f", ".env.other"])
    assert result.exit_code == 0, result.output
    binding = find_env_binding(Path(".env.other").read_text(), "SECRET")
    assert binding is not None
    assert decrypt_env_value(binding.value, other_key) == "s3cret"


def test_env_set_appends_new_line(
    write, runner, monkeypatch, env_key, reload_dotenv_files
):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
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
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", 'A="x" SECRET=old\n')
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output
    content = Path(".env.dev").read_text()
    assert content.startswith('A="x" SECRET=encrypted:')
    assert content.count("SECRET=") == 1
    assert parse_dotenv(".env.dev") == {"A": "x", "SECRET": "new"}


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("not-a-key", "not a valid key"),
        ("", "empty value"),
        (None, "PLAIN_ENV_KEY is not set"),
    ],
)
def test_env_set_fails_when_the_key_is_unusable(runner, monkeypatch, key, expected):
    """Malformed, empty and absent are one failure with three explanations."""
    if key is not None:
        monkeypatch.setenv("PLAIN_ENV_KEY", key)
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code != 0
    assert expected in result.output
    assert not Path(".env.dev").exists()


def test_env_set_refuses_to_wait_on_a_tty(runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    monkeypatch.setattr("plain.dev.env._stdin_is_a_tty", lambda: True)
    result = runner.invoke(env_cli, ["set", "SECRET"])
    assert result.exit_code != 0
    assert "Pass VALUE" in result.output
    assert not Path(".env.dev").exists()


def test_env_set_reads_value_from_stdin(runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    pem = "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
    result = runner.invoke(env_cli, ["set", "PEM"], input=pem)
    assert result.exit_code == 0, result.output
    # Exactly one trailing newline is stripped
    assert parse_dotenv(".env.dev") == {"PEM": pem.removesuffix("\n")}


def test_env_set_reports_binary_stdin_as_a_value_problem(runner, monkeypatch, env_key):
    """A key that works must not be blamed for a value that isn't text."""
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    result = runner.invoke(env_cli, ["set", "BLOB"], input=b"\xff\xfe\x00")
    assert result.exit_code != 0
    assert "not valid UTF-8" in result.output
    assert "not a valid key" not in result.output
    assert not Path(".env.dev").exists()


def test_env_set_creates_file(runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret", "-f", ".env.other"])
    assert result.exit_code == 0, result.output
    assert Path(".env.other").read_text().startswith("SECRET=encrypted:")
    assert not Path(".env.dev").exists()


def test_env_set_warns_when_a_higher_precedence_file_wins(
    write, runner, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.local", "SECRET=from-local\n")
    write(".env.dev", "A=1\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code == 0, result.output
    assert "SECRET is also set in .env.local" in result.stderr
    assert "outranks .env.dev" in result.stderr


def test_env_set_warns_when_the_shell_wins(runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    monkeypatch.setenv("SECRET", "from-shell")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code == 0, result.output
    assert "SECRET is also set in your shell environment" in result.stderr


def test_env_set_does_not_warn_when_replacing_its_own_file(
    write, runner, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", "SECRET=old\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "new"])
    assert result.exit_code == 0, result.output
    assert "outranks" not in result.stderr


def test_env_get_decrypts(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(
        ".env.dev", f"OTHER=$(exit 1)\nSECRET={encrypt_env_value('s3cret', env_key)}\n"
    )
    result = runner.invoke(env_cli, ["get", "SECRET"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "s3cret\n"


def test_env_get_reports_plaintext_binding(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", 'SECRET="not encrypted"\n')
    result = runner.invoke(env_cli, ["get", "SECRET"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "not encrypted\n"
    assert "not encrypted (printing it as written)" in result.stderr


def test_env_get_wrong_key_fails_clearly(write, runner, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV_KEY", generate_env_key())
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    result = runner.invoke(env_cli, ["get", "SECRET"])
    assert result.exit_code != 0
    assert "does not decrypt SECRET" in result.output


def test_env_get_from_a_file_under_another_key(write, runner, monkeypatch, env_key):
    """`-f` reads a file the loaded ladder can't decrypt, which is the point of `-f`."""
    other_key = generate_env_key()
    write(".env.dev", f"SECRET={encrypt_env_value('dev', env_key)}\n")
    write(".env.other", f"SECRET={encrypt_env_value('other', other_key)}\n")
    monkeypatch.setenv("PLAIN_ENV_KEY", other_key)
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
    result = runner.invoke(env_cli, ["init"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "URL in .env.dev references SECRET" in result.output


# --- the key store ---


def test_loader_resolves_the_key_from_the_store_by_id(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    store_env_key(env_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"
    # The key is used, not exported.
    assert "PLAIN_ENV_KEY" not in os.environ


def test_id_line_may_come_from_another_file_in_the_ladder(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    store_env_key(env_key)
    write(".env.dev.local", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_missing_stored_key_names_the_id_and_unlock(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "SECRET in .env.dev" in message
    assert env_key_id(env_key) in message
    assert "plain env unlock" in message


def test_environment_key_wins_over_the_store(write, monkeypatch, env_key):
    """A sandbox sets PLAIN_ENV_KEY and has no store."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_environment_key_that_is_not_the_named_key_raises(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    other_key = generate_env_key()
    monkeypatch.setenv("PLAIN_ENV_KEY", other_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert env_key_id(other_key) in message
    assert env_key_id(env_key) in message
    assert "not the key" in message


@pytest.mark.parametrize("name", ["PLAIN_ENV_KEY", "DEV_ENV_KEY"])
def test_leftover_op_read_line_gets_the_migration_hint(
    write, monkeypatch, env_key, name
):
    """The first version committed DEV_ENV_KEY=$(op read ...); it is literal text now."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(
        ".env.dev",
        f'{name}=$(op read "op://Envs/app/DEV_ENV_KEY")\n'
        f"SECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    message = str(excinfo.value)
    assert "no longer run" in message
    assert "plain env unlock" in message
    assert "op://" not in message


def test_malformed_key_id_is_rejected(write, monkeypatch, env_key):
    """The id names a file in the store, so it is validated before it is used as a path."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID=../../etc/passwd\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    assert "not a key id" in str(excinfo.value)
    assert "passwd" not in str(excinfo.value)


def test_child_process_with_values_already_bound_needs_no_key(
    write, monkeypatch, env_key
):
    """`plain dev` children inherit the decrypted values, and never touch the key."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("SECRET", "s3cret")
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_parse_dotenv_resolves_the_key_from_the_store(write, env_key):
    store_env_key(env_key)
    write(
        ".env.dev",
        f"SECRET={encrypt_env_value('s3cret', env_key)}\nPLAIN_ENV_KEY_ID={env_key_id(env_key)}\n",
    )
    assert parse_dotenv(".env.dev")["SECRET"] == "s3cret"
    assert "PLAIN_ENV_KEY" not in os.environ


# --- plain env init / set / load, end to end ---


def test_env_init_set_and_load(runner, monkeypatch, reload_dotenv_files):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    assert runner.invoke(env_cli, ["init"]).exit_code == 0
    assert runner.invoke(env_cli, ["set", "SECRET", "s3cret"]).exit_code == 0
    reload_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"
    assert "PLAIN_ENV_KEY" not in os.environ


# --- plain env unlock / lock ---


def test_env_unlock_stores_the_key_and_names_it_in_the_file(write, runner, env_key):
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    result = runner.invoke(env_cli, ["unlock"], input=env_key + "\n")
    assert result.exit_code == 0, result.output
    assert stored_env_key_path(env_key_id(env_key)).read_text().strip() == env_key
    content = Path(".env.dev").read_text()
    assert f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}" in content
    assert content.startswith("SECRET=")  # the rest of the file is untouched
    assert env_key not in result.output


def test_env_unlock_a_file_that_already_names_the_key(write, runner, env_key):
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    result = runner.invoke(env_cli, ["unlock"], input=env_key)
    assert result.exit_code == 0, result.output
    assert stored_env_key_path(env_key_id(env_key)).exists()
    assert Path(".env.dev").read_text() == f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n"


def test_env_unlock_rejects_a_key_the_file_does_not_name(write, runner, env_key):
    other_key = generate_env_key()
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    result = runner.invoke(env_cli, ["unlock"], input=other_key)
    assert result.exit_code != 0
    assert "names key" in result.output
    assert not stored_env_key_path(env_key_id(other_key)).exists()


def test_env_unlock_rejects_a_key_that_does_not_decrypt_the_file(
    write, runner, env_key
):
    other_key = generate_env_key()
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    result = runner.invoke(env_cli, ["unlock"], input=other_key)
    assert result.exit_code != 0
    assert "does not decrypt SECRET" in result.output
    assert not stored_env_key_path(env_key_id(other_key)).exists()
    assert "PLAIN_ENV_KEY_ID" not in Path(".env.dev").read_text()


def test_env_unlock_replaces_a_leftover_key_line(write, runner, env_key):
    """The first version named the key with PLAIN_ENV_KEY=$(op read ...); the id line takes its place."""
    token = encrypt_env_value("s3cret", env_key)
    write(
        ".env.dev",
        "# header\n"
        'PLAIN_ENV_KEY=$(op read "op://Envs/app/PLAIN_ENV_KEY")\n'
        f"SECRET={token}\n",
    )
    result = runner.invoke(env_cli, ["unlock"], input=env_key)
    assert result.exit_code == 0, result.output
    assert "Replaced the PLAIN_ENV_KEY= line" in result.output
    assert Path(".env.dev").read_text() == (
        f"# header\nPLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={token}\n"
    )
    assert "Warning" not in result.output


def test_env_unlock_warns_about_a_key_line_next_to_an_id_line(write, runner, env_key):
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n"
        'PLAIN_ENV_KEY=$(op read "op://Envs/app/PLAIN_ENV_KEY")\n',
    )
    result = runner.invoke(env_cli, ["unlock"], input=env_key)
    assert result.exit_code == 0, result.output
    assert "delete that line" in result.stderr


def test_env_unlock_rejects_a_malformed_key(runner):
    result = runner.invoke(env_cli, ["unlock"], input="not-a-key\n")
    assert result.exit_code != 0
    assert "not a valid key" in result.output


def test_env_unlock_refuses_to_wait_on_a_tty(runner, monkeypatch):
    monkeypatch.setattr("plain.dev.env._stdin_is_a_tty", lambda: True)
    result = runner.invoke(env_cli, ["unlock"])
    assert result.exit_code != 0
    assert "Pipe the key in" in result.output


def test_env_lock_removes_the_stored_key(write, runner, env_key):
    store_env_key(env_key)
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    result = runner.invoke(env_cli, ["lock"])
    assert result.exit_code == 0, result.output
    assert not stored_env_key_path(env_key_id(env_key)).exists()

    result = runner.invoke(env_cli, ["lock"])
    assert result.exit_code == 0, result.output
    assert "not on this machine" in result.output


def test_env_lock_without_an_id_line_fails(runner):
    result = runner.invoke(env_cli, ["lock"])
    assert result.exit_code != 0
    assert "does not name a key" in result.output


# --- plain env rotate ---


def test_env_rotate_reencrypts_every_value_and_keeps_the_old_key(
    write, runner, env_key
):
    store_env_key(env_key)
    write(
        ".env.dev",
        "# header\n"
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n"
        "PLAIN_DEBUG=true\n"
        f"export A={encrypt_env_value('a', env_key)}  # inline\n"
        f"B={encrypt_env_value('b', env_key)}\n",
    )
    result = runner.invoke(env_cli, ["rotate"])
    assert result.exit_code == 0, result.output
    assert "Re-encrypted 2 values" in result.output

    content = Path(".env.dev").read_text()
    id_binding = find_env_binding(content, "PLAIN_ENV_KEY_ID")
    assert id_binding is not None
    new_id = id_binding.value
    assert new_id != env_key_id(env_key)
    new_key = stored_env_key_path(new_id).read_text().strip()
    assert env_key_id(new_key) == new_id
    # The old key is still on this machine, for branches that name it.
    assert stored_env_key_path(env_key_id(env_key)).exists()

    assert parse_dotenv(".env.dev") == {
        "PLAIN_ENV_KEY_ID": new_id,
        "PLAIN_DEBUG": "true",
        "A": "a",
        "B": "b",
    }
    assert content.startswith("# header\n")
    assert "export A=encrypted:" in content
    assert "  # inline\n" in content
    for name in ("A", "B"):
        binding = find_env_binding(content, name)
        assert binding is not None
        with pytest.raises(InvalidToken):
            decrypt_env_value(binding.value, env_key)


def test_env_rotate_fails_when_a_value_does_not_decrypt(write, runner, env_key):
    store_env_key(env_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n"
        f"A={encrypt_env_value('a', generate_env_key())}\n",
    )
    before = Path(".env.dev").read_text()
    result = runner.invoke(env_cli, ["rotate"])
    assert result.exit_code != 0
    assert "A in .env.dev does not decrypt" in result.output
    assert Path(".env.dev").read_text() == before


def test_env_rotate_names_the_key_in_a_file_that_did_not(
    write, runner, monkeypatch, env_key
):
    """A file still unlocked by PLAIN_ENV_KEY in the environment gets an id line."""
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", f"A={encrypt_env_value('a', env_key)}\n")
    result = runner.invoke(env_cli, ["rotate"])
    assert result.exit_code == 0, result.output
    content = Path(".env.dev").read_text()
    binding = find_env_binding(content, "PLAIN_ENV_KEY_ID")
    assert binding is not None
    assert stored_env_key_path(binding.value).exists()


# --- hardening (from review) ---


def test_env_lock_refuses_a_malformed_id(write, runner, tmp_path):
    """The id names a file in the store; a bad one must never reach unlink."""
    victim = tmp_path / "victim"
    victim.write_text("keep me")
    write(".env.dev", f"PLAIN_ENV_KEY_ID={victim}\n")
    result = runner.invoke(env_cli, ["lock"])
    assert result.exit_code != 0
    assert "not a key id" in result.output
    assert victim.exists()


def test_store_fixes_permissions_of_an_existing_store(isolated_env_keys, env_key):
    isolated_env_keys.mkdir(mode=0o755)
    stale = stored_env_key_path(env_key_id(env_key))
    stale.write_text("old")
    os.chmod(stale, 0o644)
    path = store_env_key(env_key)
    assert path == stale
    assert os.stat(isolated_env_keys).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert path.read_text().strip() == env_key


def test_store_refuses_a_symlink(isolated_env_keys, tmp_path, env_key):
    isolated_env_keys.mkdir()
    target = tmp_path / "elsewhere"
    target.write_text("untouched")
    stored_env_key_path(env_key_id(env_key)).symlink_to(target)
    with pytest.raises(ImproperlyConfigured) as excinfo:
        store_env_key(env_key)
    assert "symlink" in str(excinfo.value)
    assert target.read_text() == "untouched"


def test_a_value_cannot_reference_the_key(write, monkeypatch, env_key):
    """No file, committed or not, can capture the key into a variable."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", "LEAK=$PLAIN_ENV_KEY\n")
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    assert "LEAK in .env.dev references PLAIN_ENV_KEY" in str(excinfo.value)
    assert env_key not in str(excinfo.value)
    assert "LEAK" not in os.environ


def test_a_key_line_in_one_file_cannot_be_captured_by_another(
    write, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.dev.local", f"PLAIN_ENV_KEY={env_key}\n")
    write(".env.dev", "LEAK=$PLAIN_ENV_KEY\n")
    with pytest.raises(ImproperlyConfigured):
        load_dotenv_files()
    assert "LEAK" not in os.environ
    assert "PLAIN_ENV_KEY" not in os.environ


def test_leftover_op_read_error_does_not_echo_the_value(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(
        ".env.dev",
        'PLAIN_ENV_KEY=$(op read "op://Envs/app/PLAIN_ENV_KEY")\n'
        f"SECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    assert "op://" not in str(excinfo.value)


def test_env_init_refuses_a_file_with_encrypted_values(write, runner, env_key):
    """Running init instead of unlock on a migrated file must not strand its values."""
    before = f"SECRET={encrypt_env_value('s3cret', env_key)}\n"
    write(".env.dev", before)
    result = runner.invoke(env_cli, ["init"])
    assert result.exit_code != 0
    assert "plain env unlock" in result.output
    assert Path(".env.dev").read_text() == before
    assert not list(stored_env_key_path("0" * 12).parent.glob("*"))


def test_env_rotate_warns_when_the_old_key_is_in_the_environment(
    write, runner, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", f"A={encrypt_env_value('a', env_key)}\n")
    result = runner.invoke(env_cli, ["rotate"])
    assert result.exit_code == 0, result.output
    assert "still holds the old key" in result.stderr


def test_env_rotate_error_names_the_file_flag(write, runner, env_key):
    store_env_key(env_key)
    write(
        ".env.other",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n"
        f"A={encrypt_env_value('a', generate_env_key())}\n",
    )
    result = runner.invoke(env_cli, ["rotate", "-f", ".env.other"])
    assert result.exit_code != 0
    assert "plain env set A -f .env.other" in result.output


def test_env_unlock_replaces_the_key_line_in_a_crlf_file(runner, env_key):
    token = encrypt_env_value("s3cret", env_key)
    Path(".env.dev").write_bytes(
        b'# header\r\nPLAIN_ENV_KEY=$(op read "op://x")\r\nSECRET='
        + token.encode()
        + b"\r\n"
    )
    result = runner.invoke(env_cli, ["unlock"], input=env_key)
    assert result.exit_code == 0, result.output
    assert Path(".env.dev").read_bytes() == (
        b"# header\r\nPLAIN_ENV_KEY_ID="
        + env_key_id(env_key).encode()
        + b"\r\nSECRET="
        + token.encode()
        + b"\r\n"
    )


# --- the loader owns its two variables ---


def test_id_line_is_never_bound_into_the_environment(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    store_env_key(env_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"
    assert "PLAIN_ENV_KEY_ID" not in os.environ
    assert not any(k.startswith("PLAIN_ENV_KEY") for k in os.environ)


def test_key_from_the_environment_is_consumed(write, monkeypatch, env_key):
    """A sandbox sets the key; after the load nothing under the loader can read it."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"
    assert "PLAIN_ENV_KEY" not in os.environ


def test_key_is_consumed_even_when_nothing_needs_decrypting(
    write, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", "PLAIN_DEBUG=true\n")
    load_dotenv_files()
    assert "PLAIN_ENV_KEY" not in os.environ


def test_key_line_in_a_gitignored_file_is_consumed(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.dev.local", f"PLAIN_ENV_KEY={env_key}\n")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"
    assert "PLAIN_ENV_KEY" not in os.environ


def test_environment_key_wins_over_a_key_line_in_a_file(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev.local", f"PLAIN_ENV_KEY={generate_env_key()}\n")
    write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_consumed_key_still_serves_plain_env_commands(
    write, runner, monkeypatch, env_key
):
    """`plain env` loads without decrypting, then needs the key it consumed."""
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
    assert result.exit_code == 0, result.output
    assert parse_dotenv(".env.dev")["SECRET"] == "s3cret"


def test_env_unlock_replaces_a_legacy_dev_env_key_line(write, runner, env_key):
    token = encrypt_env_value("s3cret", env_key)
    write(
        ".env.dev",
        f'DEV_ENV_KEY=$(op read "op://Envs/app/DEV_ENV_KEY")\nSECRET={token}\n',
    )
    result = runner.invoke(env_cli, ["unlock"], input=env_key)
    assert result.exit_code == 0, result.output
    assert "Replaced the DEV_ENV_KEY= line" in result.output
    assert Path(".env.dev").read_text() == (
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={token}\n"
    )


# --- from the second review ---


def test_an_exported_key_id_is_ignored(write, monkeypatch, env_key):
    """The id comes from files only; a stale one in the shell can't override it."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    monkeypatch.setenv("PLAIN_ENV_KEY_ID", "0" * 12)
    store_env_key(env_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_an_empty_id_line_does_not_block_a_later_one(write, monkeypatch, env_key):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    store_env_key(env_key)
    write(".env.dev.local", "PLAIN_ENV_KEY_ID=\n")
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    load_dotenv_files()
    assert os.environ["SECRET"] == "s3cret"


def test_load_dotenv_does_not_carry_an_id_across_files(write, env_key):
    key_a, key_b = env_key, generate_env_key()
    store_env_key(key_a)
    write(
        "a.env",
        f"PLAIN_ENV_KEY_ID={env_key_id(key_a)}\nA={encrypt_env_value('a', key_a)}\n",
    )
    write("b.env", f"B={encrypt_env_value('b', key_b)}\n")
    assert load_dotenv("a.env")
    assert os.environ["A"] == "a"
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv("b.env")
    assert "no key is available" in str(excinfo.value)


def test_a_corrupt_stored_key_is_reported_as_the_stores_problem(
    write, monkeypatch, env_key
):
    monkeypatch.setenv("PLAIN_ENV", "dev")
    path = store_env_key(env_key)
    path.write_text("not-a-key\n")
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_dotenv_files()
    assert str(path) in str(excinfo.value)
    assert "plain env unlock" in str(excinfo.value)


def test_store_refuses_a_symlinked_directory(isolated_env_keys, tmp_path, env_key):
    real = tmp_path / "elsewhere"
    real.mkdir()
    isolated_env_keys.symlink_to(real)
    with pytest.raises(ImproperlyConfigured) as excinfo:
        store_env_key(env_key)
    assert "symlink" in str(excinfo.value)
    assert not list(real.iterdir())


def test_parse_dotenv_omits_the_key_line(write, env_key):
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY={env_key}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    result = parse_dotenv(".env.dev")
    assert result == {"SECRET": "s3cret"}
    assert env_key not in result.values()


def test_env_init_refuses_when_another_ladder_file_names_a_key(write, runner, env_key):
    write(".env", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    result = runner.invoke(env_cli, ["init"])
    assert result.exit_code != 0
    assert ".env already names key" in result.output
    assert not Path(".env.dev").exists()


def test_env_rotate_refuses_when_another_ladder_file_has_encrypted_values(
    write, runner, env_key
):
    store_env_key(env_key)
    write(
        ".env.dev",
        f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\nA={encrypt_env_value('a', env_key)}\n",
    )
    write(".env", f"B={encrypt_env_value('b', env_key)}\n")
    before = Path(".env.dev").read_text()
    result = runner.invoke(env_cli, ["rotate"])
    assert result.exit_code != 0
    assert ".env also has encrypted values" in result.output
    assert Path(".env.dev").read_text() == before


def test_env_lock_does_not_fall_back_to_the_ladders_key(write, runner, env_key):
    store_env_key(env_key)
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    write(".env.other", "X=1\n")
    result = runner.invoke(env_cli, ["lock", "-f", ".env.other"])
    assert result.exit_code != 0
    assert "does not name a key" in result.output
    assert stored_env_key_path(env_key_id(env_key)).exists()


def test_environment_key_for_another_file_does_not_block_the_store(
    write, runner, monkeypatch, env_key
):
    other_key = generate_env_key()
    store_env_key(other_key)
    monkeypatch.setenv("PLAIN_ENV_KEY", env_key)
    write(".env.dev", f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    write(".env.other", f"PLAIN_ENV_KEY_ID={env_key_id(other_key)}\n")
    result = runner.invoke(env_cli, ["set", "SECRET", "s3cret", "-f", ".env.other"])
    assert result.exit_code == 0, result.output
    binding = find_env_binding(Path(".env.other").read_text(), "SECRET")
    assert binding is not None
    assert decrypt_env_value(binding.value, other_key) == "s3cret"


def test_env_unlock_rejects_binary_stdin(runner):
    result = runner.invoke(env_cli, ["unlock"], input=b"\xff\xfe\x00")
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "not a valid key" in result.output


def test_env_unlock_warns_about_a_second_key_line(write, runner, env_key):
    write(
        ".env.dev",
        'PLAIN_ENV_KEY=$(op read "op://a")\nDEV_ENV_KEY=$(op read "op://b")\n'
        f"SECRET={encrypt_env_value('s3cret', env_key)}\n",
    )
    result = runner.invoke(env_cli, ["unlock"], input=env_key)
    assert result.exit_code == 0, result.output
    content = Path(".env.dev").read_text()
    assert content.startswith(f"PLAIN_ENV_KEY_ID={env_key_id(env_key)}\n")
    assert "DEV_ENV_KEY=$(op read" in content
    assert "still has a DEV_ENV_KEY= line" in result.stderr
