import importlib.metadata
import os
from pathlib import Path

import plain.runtime
from click.testing import CliRunner
from dev_test_helpers import sandbox
from plain.cli.core import cli as plain_cli
from plain.dev import env as env_module
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
from plain.test import patch, raises

# --- crypto helpers ---


def test_encrypt_decrypt_roundtrip():
    with sandbox():
        env_key = generate_env_key()
        encrypted = encrypt_env_value("hunter2", env_key)
        assert encrypted.startswith("encrypted:")
        assert is_encrypted_value(encrypted)
        assert decrypt_env_value(encrypted, env_key) == "hunter2"


def test_encrypt_decrypt_roundtrip_multiline():
    with sandbox():
        env_key = generate_env_key()
        pem = "-----BEGIN PRIVATE KEY-----\nabc\ndef\n-----END PRIVATE KEY-----\n"
        encrypted = encrypt_env_value(pem, env_key)
        assert "\n" not in encrypted
        assert decrypt_env_value(encrypted, env_key) == pem


def test_is_encrypted_value_is_a_prefix_test():
    """The tag is syntax, not a token shape — anything starting with it is encrypted."""
    with sandbox():
        env_key = generate_env_key()
        assert is_encrypted_value(encrypt_env_value("x", env_key))
        assert is_encrypted_value("encrypted:not-a-real-token")
        assert not is_encrypted_value("see encrypted:gAAAA")
        assert not is_encrypted_value("plain")


# --- loader ---


def test_loader_decrypts_with_key_in_environ():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == "s3cret"


def test_key_from_env_local_decrypts_env_dev():
    """`.env.local` loads before `.env.dev`; its key line is what decrypts `.env.dev`."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env.local", f"DEV_ENV_KEY={env_key}\n")
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == "s3cret"


def test_key_after_values_in_same_file():
    """Decryption happens after the whole file parses, so order within a file doesn't matter."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        box.write(
            ".env.dev",
            f"SECRET={encrypt_env_value('s3cret', env_key)}\nDEV_ENV_KEY={env_key}\n",
        )
        load_dotenv_files()
        assert os.environ["SECRET"] == "s3cret"


def test_key_from_command_substitution():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env.local", f"DEV_ENV_KEY=$(echo {env_key})\n")
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        load_dotenv_files()
        assert os.environ["DEV_ENV_KEY"] == env_key
        assert os.environ["SECRET"] == "s3cret"


def test_missing_key_raises_naming_variable_and_file():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        message = str(caught.exception)
        assert "SECRET" in message
        assert ".env.dev" in message
        assert "DEV_ENV_KEY" in message
        assert ".env.dev.local" in message
        assert "SECRET" not in os.environ


def test_missing_key_hint_without_plain_env_names_env_local():
    with sandbox() as box:
        env_key = generate_env_key()
        box.write(".env", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        assert ".env.local" in str(caught.exception)
        assert ".env.dev.local" not in str(caught.exception)


def test_empty_key_blames_the_command_that_should_have_produced_it():
    """An empty DEV_ENV_KEY means its `$(...)` lookup failed, not that it's unset."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = ""
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        message = str(caught.exception)
        assert "empty value" in message
        assert "op read" in message
        assert "is not set" not in message


def test_wrong_key_raises():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = generate_env_key()
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        message = str(caught.exception)
        assert "SECRET" in message
        assert ".env.dev" in message
        assert "does not decrypt" in message
        assert "SECRET" not in os.environ


def test_existing_environ_value_is_left_alone():
    """A key already in os.environ wins; its encrypted line is never decrypted (no key needed)."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["SECRET"] = "from-shell"
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == "from-shell"


def test_bound_key_with_multiline_duplicate_in_later_file():
    """A lower-precedence multi-line duplicate is skipped whole — its inner lines aren't bindings."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env.local", "SECRET=from-local\n")
        box.write(".env.dev", 'SECRET="l1\nFOO=bar\nl3"\nAFTER=1\n')
        load_dotenv_files()
        assert os.environ["SECRET"] == "from-local"
        assert "FOO" not in os.environ
        assert os.environ["AFTER"] == "1"


def test_bound_key_never_runs_its_commands():
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["SECRET"] = "from-shell"
        box.write(
            ".env.dev",
            'SECRET=$(touch marker-unquoted)\nSECRET="$(touch marker-quoted)"\n',
        )
        load_dotenv_files()
        assert os.environ["SECRET"] == "from-shell"
        assert not Path("marker-unquoted").exists()
        assert not Path("marker-quoted").exists()


def test_encrypted_value_in_earlier_file_beats_plain_value_in_later_file():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.local", f"SECRET={encrypt_env_value('from-local', env_key)}\n")
        box.write(".env.dev", "SECRET=from-dev\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == "from-local"


def test_decrypted_plaintext_is_bound_literally():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = env_key
        plaintext = "cost is $HOME and $(echo x) and ${HOME}"
        box.write(".env.dev", f"SECRET={encrypt_env_value(plaintext, env_key)}\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == plaintext


# --- the `encrypted:` tag is syntax ---


def test_encrypted_prefix_inside_longer_value_is_plain_text():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        encrypted = encrypt_env_value("s3cret", env_key)
        box.write(".env.dev", f"NOTE=see {encrypted}\n")
        load_dotenv_files()  # no key needed, nothing to decrypt
        assert os.environ["NOTE"] == f"see {encrypted}"


def test_quoted_encrypted_prefix_is_plain_text():
    """Quoting is the escape hatch for a literal value that starts with the tag."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env.dev", "SINGLE='encrypted:aes'\nDOUBLE=\"encrypted:aes\"\n")
        load_dotenv_files()  # no key needed
        assert os.environ["SINGLE"] == "encrypted:aes"
        assert os.environ["DOUBLE"] == "encrypted:aes"


def test_unquoted_malformed_encrypted_value_raises_with_quoting_hint():
    """An unquoted `encrypted:` value that doesn't decrypt is a mistake, not plain text."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", "MODE=encrypted:aes\n")
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        message = str(caught.exception)
        assert "MODE" in message
        assert ".env.dev" in message
        assert "quote it" in message
        assert "MODE" not in os.environ


# --- references to encrypted values ---


def test_reference_to_encrypted_value_in_same_file_raises():
    """`B=$A` where A is encrypted used to expand to A's ciphertext."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(
            ".env.dev",
            f"SECRET={encrypt_env_value('s3cret', env_key)}\nURL=https://$SECRET@example.com\n",
        )
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        message = str(caught.exception)
        assert "URL in .env.dev references SECRET" in message
        assert "can't be referenced from other values" in message
        assert "URL" not in os.environ


def test_reference_to_encrypted_value_in_earlier_file_raises():
    """Across files it used to expand to an empty string."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.local", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        box.write(".env.dev", "URL=${SECRET}\n")
        with raises(ImproperlyConfigured) as caught:
            load_dotenv_files()
        assert "URL in .env.dev references SECRET" in str(caught.exception)


def test_reference_to_a_shadowed_encrypted_value_uses_the_bound_value():
    """A shadowed encrypted line isn't the value of the name, so referencing it is fine."""
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["PLAIN_ENV"] = "dev"
        os.environ["SECRET"] = "from-shell"
        box.write(
            ".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nURL=$SECRET\n"
        )
        load_dotenv_files()  # no key needed
        assert os.environ["URL"] == "from-shell"


# --- one parser ---


def test_digit_leading_key_is_skipped_by_loader_and_find_env_binding():
    """`find_env_binding` is the loader's parser in raw mode, so they agree on what's a binding."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "dev"
        content = "1BAD=x\nGOOD=y\n"
        box.write(".env.dev", content)
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


def test_load_dotenv_decrypts_single_file():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write("custom.env", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        assert load_dotenv("custom.env") is True
        assert os.environ["SECRET"] == "s3cret"


def test_load_dotenv_without_decrypt_leaves_encrypted_values_unbound():
    with sandbox() as box:
        env_key = generate_env_key()
        box.write(
            "custom.env", f"PLAIN=x\nSECRET={encrypt_env_value('s3cret', env_key)}\n"
        )
        assert load_dotenv("custom.env", decrypt=False) is True
        assert os.environ["PLAIN"] == "x"
        assert "SECRET" not in os.environ


def test_parse_dotenv_decrypts():
    with sandbox() as box:
        env_key = generate_env_key()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(
            ".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nPLAIN=x\n"
        )
        assert parse_dotenv(".env.dev") == {"SECRET": "s3cret", "PLAIN": "x"}
        assert "SECRET" not in os.environ


def test_parse_dotenv_uses_the_key_line_in_the_same_file():
    with sandbox() as box:
        env_key = generate_env_key()
        box.write(
            ".env.dev",
            f"DEV_ENV_KEY={env_key}\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
        )
        assert parse_dotenv(".env.dev")["SECRET"] == "s3cret"
        assert "DEV_ENV_KEY" not in os.environ


def test_parse_dotenv_without_key_raises():
    with sandbox() as box:
        env_key = generate_env_key()
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        with raises(ImproperlyConfigured) as caught:
            parse_dotenv(".env.dev")
        assert "SECRET" in str(caught.exception)


# --- plain env CLI ---


def test_plain_env_is_registered_as_a_cli_entry_point():
    """plain.dev contributes `plain env` through the `plain.cli` entry point group."""
    entry_points = importlib.metadata.entry_points(group="plain.cli")
    assert entry_points["env"].load() is env_cli


def test_plain_env_runs_without_runtime_setup():
    """`plain env` is the command you run when loading the app would fail."""
    with sandbox():
        setup_calls = []
        with patch(plain.runtime, "setup", lambda: setup_calls.append("setup")):
            result = CliRunner().invoke(plain_cli, ["env", "--help"], prog_name="plain")

        assert result.exit_code == 0, result.output
        assert "set" in result.output
        assert setup_calls == []


def test_env_key_prints_a_fernet_key():
    with sandbox():
        runner = CliRunner()
        from cryptography.fernet import Fernet

        result = runner.invoke(env_cli, ["key"])
        assert result.exit_code == 0, result.output
        key = result.stdout.strip()
        assert len(key) == 44
        Fernet(key.encode())


def test_env_key_works_on_a_clone_with_no_key():
    """`plain env key` is the fix for a missing key, so it can't need one itself."""
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        result = runner.invoke(env_cli, ["key"])
        assert result.exit_code == 0, result.output
        assert len(result.stdout.strip()) == 44
        assert "SECRET" not in os.environ


def test_env_set_rotates_values_encrypted_with_an_older_key():
    """Existing values are never validated against the key, so a new key can be used."""
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        box.write(".env.dev", f"SECRET={encrypt_env_value('old', env_key)}\n")
        os.environ["DEV_ENV_KEY"] = generate_env_key()
        result = runner.invoke(env_cli, ["set", "SECRET", "new"])
        assert result.exit_code == 0, result.output
        assert parse_dotenv(".env.dev") == {"SECRET": "new"}


def test_env_set_appends_new_line():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", "FIRST=1\n")
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
        assert result.exit_code == 0, result.output
        assert "s3cret" not in result.output

        content = Path(".env.dev").read_text()
        assert content.startswith("FIRST=1\nSECRET=encrypted:")
        assert content.endswith("\n")
        os.environ["PLAIN_ENV"] = "dev"
        box.reload_dotenv_files()
        assert os.environ["SECRET"] == "s3cret"


def test_env_set_replaces_single_line_value():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", "A=1\nexport SECRET = old # keep me\nB=2\n")
        result = runner.invoke(env_cli, ["set", "SECRET", "new"])
        assert result.exit_code == 0, result.output

        lines = Path(".env.dev").read_text().splitlines()
        assert lines[0] == "A=1"
        assert lines[1].startswith("export SECRET=encrypted:")
        assert lines[1].endswith(" # keep me")
        assert lines[2] == "B=2"
        assert len(lines) == 3


def test_env_set_replaces_multiline_double_quoted_value():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        before = "# header\nA=1\n"
        after = "\n\nB='multi\nline'\n"
        box.write(
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
        assert parse_dotenv(".env.dev") == {
            "A": "1",
            "SECRET": "new",
            "B": "multi\nline",
        }


def test_env_set_preserves_crlf_line_endings():
    with sandbox():
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
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


def test_env_set_replaces_second_binding_on_a_line():
    """`A="x" SECRET=old` binds both in the loader, so `set` must find SECRET there too."""
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", 'A="x" SECRET=old\n')
        result = runner.invoke(env_cli, ["set", "SECRET", "new"])
        assert result.exit_code == 0, result.output
        content = Path(".env.dev").read_text()
        assert content.startswith('A="x" SECRET=encrypted:')
        assert content.count("SECRET=") == 1
        assert parse_dotenv(".env.dev") == {"A": "x", "SECRET": "new"}


def test_env_set_fails_with_malformed_key():
    with sandbox():
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = "not-a-key"
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
        assert result.exit_code != 0
        assert "not a valid key" in result.output
        assert not Path(".env.dev").exists()


def test_env_set_fails_with_empty_key():
    with sandbox():
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = ""
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
        assert result.exit_code != 0
        assert "empty value" in result.output
        assert "op read" in result.output
        assert not Path(".env.dev").exists()


def test_env_set_refuses_to_wait_on_a_tty():
    with sandbox():
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        with patch(env_module, "_stdin_is_a_tty", lambda: True):
            result = runner.invoke(env_cli, ["set", "SECRET"])
        assert result.exit_code != 0
        assert "Pass VALUE" in result.output
        assert not Path(".env.dev").exists()


def test_env_set_reads_value_from_stdin():
    with sandbox():
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        pem = "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
        result = runner.invoke(env_cli, ["set", "PEM"], input=pem)
        assert result.exit_code == 0, result.output
        # Exactly one trailing newline is stripped
        assert parse_dotenv(".env.dev") == {"PEM": pem.removesuffix("\n")}


def test_env_set_reports_binary_stdin_as_a_value_problem():
    """A key that works must not be blamed for a value that isn't text."""
    with sandbox():
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        result = runner.invoke(env_cli, ["set", "BLOB"], input=b"\xff\xfe\x00")
        assert result.exit_code != 0
        assert "not valid UTF-8" in result.output
        assert "not a valid key" not in result.output
        assert not Path(".env.dev").exists()


def test_env_set_creates_file():
    with sandbox():
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret", "-f", ".env.other"])
        assert result.exit_code == 0, result.output
        assert Path(".env.other").read_text().startswith("SECRET=encrypted:")
        assert not Path(".env.dev").exists()


def test_env_set_fails_without_key():
    with sandbox():
        runner = CliRunner()
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
        assert result.exit_code != 0
        assert "DEV_ENV_KEY is not set" in result.output
        assert not Path(".env.dev").exists()


def test_env_set_warns_when_a_higher_precedence_file_wins():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.local", "SECRET=from-local\n")
        box.write(".env.dev", "A=1\n")
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
        assert result.exit_code == 0, result.output
        assert "SECRET is also set in .env.local" in result.stderr
        assert "outranks .env.dev" in result.stderr


def test_env_set_warns_when_the_shell_wins():
    with sandbox():
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        os.environ["SECRET"] = "from-shell"
        result = runner.invoke(env_cli, ["set", "SECRET", "s3cret"])
        assert result.exit_code == 0, result.output
        assert "SECRET is also set in your shell environment" in result.stderr


def test_env_set_does_not_warn_when_replacing_its_own_file():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", "SECRET=old\n")
        result = runner.invoke(env_cli, ["set", "SECRET", "new"])
        assert result.exit_code == 0, result.output
        assert "outranks" not in result.stderr


def test_env_get_decrypts():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(
            ".env.dev",
            f"OTHER=$(exit 1)\nSECRET={encrypt_env_value('s3cret', env_key)}\n",
        )
        result = runner.invoke(env_cli, ["get", "SECRET"])
        assert result.exit_code == 0, result.output
        assert result.stdout == "s3cret\n"


def test_env_get_reports_plaintext_binding():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = env_key
        box.write(".env.dev", 'SECRET="not encrypted"\n')
        result = runner.invoke(env_cli, ["get", "SECRET"])
        assert result.exit_code == 0, result.output
        assert result.stdout == "not encrypted\n"
        assert "not encrypted (printing it as written)" in result.stderr


def test_env_get_wrong_key_fails_clearly():
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        os.environ["DEV_ENV_KEY"] = generate_env_key()
        box.write(".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\n")
        result = runner.invoke(env_cli, ["get", "SECRET"])
        assert result.exit_code != 0
        assert "does not decrypt SECRET" in result.output


def test_env_get_from_a_file_under_another_key():
    """`-f` reads a file the loaded ladder can't decrypt, which is the point of `-f`."""
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        other_key = generate_env_key()
        box.write(".env.dev", f"SECRET={encrypt_env_value('dev', env_key)}\n")
        box.write(".env.other", f"SECRET={encrypt_env_value('other', other_key)}\n")
        os.environ["DEV_ENV_KEY"] = other_key
        result = runner.invoke(env_cli, ["get", "SECRET", "-f", ".env.other"])
        assert result.exit_code == 0, result.output
        assert result.stdout == "other\n"


def test_env_get_restores_escaped_dollar_in_double_quoted_plaintext():
    with sandbox() as box:
        runner = CliRunner()
        box.write(".env.dev", 'PRICE="cost is \\$5"\n')
        result = runner.invoke(env_cli, ["get", "PRICE"])
        assert result.exit_code == 0, result.output
        assert result.output.strip().splitlines()[-1] == "cost is $5"


def test_env_reports_a_broken_env_file_without_a_traceback():
    """`plain env` runs without app setup, so it renders loader errors itself."""
    with sandbox() as box:
        env_key = generate_env_key()
        runner = CliRunner()
        box.write(
            ".env.dev", f"SECRET={encrypt_env_value('s3cret', env_key)}\nURL=$SECRET\n"
        )
        result = runner.invoke(env_cli, ["key"])
        assert result.exit_code != 0
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "URL in .env.dev references SECRET" in result.output
